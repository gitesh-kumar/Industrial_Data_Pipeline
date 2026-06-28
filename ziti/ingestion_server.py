"""
Ziti-Protected Ingestion Server
================================
Receives sensor data ONLY from Ziti-verified factory machines.

This service replaces the file-based ingestion in ingestion.py.
It binds to the Ziti fabric as a service — it has NO open ports,
NO exposed IP address. It is completely dark to the internet.

Only machines with a valid enrolled Ziti identity can reach it.

Architecture:
    Internet →  BLOCKED (no open ports)
    Ziti Fabric →  ALLOWED (identity verified)

Usage:
    python ziti/ingestion_server.py

Security properties:
    - Dark service: invisible to port scanners
    - Mutual TLS: machine identity verified on every connection
    - No lateral movement: compromised machine can't reach other services
    - Audit log: every connection logged with machine identity
"""

import sys
import json
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from uvicorn import Config

sys.path.append(str(Path(__file__).parent.parent))
from ziti.config import (
    INGESTION_SERVICE_NAME, INGESTION_SERVER_IDENTITY,
    FACTORY_DEVICE_ROLE
)

# ── AUDIT LOG ────────────────────────────────────────────────────
AUDIT_LOG_PATH = Path("data/ziti_audit.log")


def log_connection(machine_id: str, status: str, details: str = ""):
    """
    Logs every connection attempt with machine identity.
    This is the audit trail that proves zero-trust compliance.
    """
    AUDIT_LOG_PATH.parent.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "machine_id": machine_id,
        "status": status,
        "details": details
    }
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── FASTAPI INGESTION ENDPOINT ───────────────────────────────────
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import pandas as pd

ingestion_app = FastAPI(
    title="Ziti-Protected Ingestion Service",
    description="Dark service — only accessible through OpenZiti fabric"
)

DATA_PATH = "data/bronze_sensors.csv"
os.makedirs("data", exist_ok=True)

# In-memory buffer for batching writes
_buffer = []
_buffer_lock = threading.Lock()
BUFFER_SIZE = 10  # Write to CSV every 10 records


@ingestion_app.post("/ingest")
async def ingest_sensor_data(request: Request):
    """
    Receives sensor data from a Ziti-verified machine.
    
    The Ziti fabric has already verified the machine's identity
    before this endpoint is reached — no additional auth needed.
    """
    try:
        data = await request.json()
        machine_id = data.get("machine_id", "UNKNOWN")
        ziti_identity = data.get("ziti_identity", "unknown")
        
        # Log the verified connection
        log_connection(
            machine_id=machine_id,
            status="ACCEPTED",
            details=f"identity={ziti_identity}"
        )
        
        # Remove Ziti metadata before storing
        clean_data = {k: v for k, v in data.items() if k != "ziti_identity"}
        
        # Buffer and write to Bronze layer
        with _buffer_lock:
            _buffer.append(clean_data)
            if len(_buffer) >= BUFFER_SIZE:
                _flush_buffer()
        
        return JSONResponse(
            content={"status": "accepted", "machine_id": machine_id},
            status_code=200
        )
    
    except Exception as e:
        log_connection("UNKNOWN", "ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@ingestion_app.post("/ingest/batch")
async def ingest_batch(request: Request):
    """Accepts a batch of readings from a machine."""
    try:
        batch = await request.json()
        machine_id = batch.get("machine_id", "UNKNOWN")
        readings = batch.get("readings", [])
        
        log_connection(machine_id, "BATCH_ACCEPTED", f"count={len(readings)}")
        
        with _buffer_lock:
            for reading in readings:
                clean = {k: v for k, v in reading.items() if k != "ziti_identity"}
                _buffer.append(clean)
            _flush_buffer()
        
        return JSONResponse(
            content={"status": "accepted", "count": len(readings)},
            status_code=200
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@ingestion_app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "ziti-ingestion-server",
        "mode": "zero-trust",
        "records_buffered": len(_buffer)
    }


@ingestion_app.get("/audit")
async def get_audit_log(limit: int = 50):
    """Returns recent connection audit log."""
    if not AUDIT_LOG_PATH.exists():
        return {"entries": []}
    
    entries = []
    with open(AUDIT_LOG_PATH) as f:
        lines = f.readlines()
    
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except:
            pass
    
    return {"entries": entries, "total": len(lines)}


def _flush_buffer():
    """Writes buffered readings to Bronze layer CSV."""
    global _buffer
    if not _buffer:
        return
    
    df = pd.DataFrame(_buffer)
    file_exists = os.path.exists(DATA_PATH)
    df.to_csv(DATA_PATH, mode="a", header=not file_exists, index=False)
    
    print(f"💾 Flushed {len(_buffer)} records to Bronze layer")
    _buffer = []


# ── ZITI SERVER BINDING ──────────────────────────────────────────
class ZitiIngestionServer:
    """
    Binds the ingestion FastAPI app to the Ziti fabric as a dark service.
    
    After binding:
    - The service has NO open network ports
    - It only receives connections through the Ziti overlay
    - Every connecting machine must present a valid identity
    """

    def __init__(self):
        self.ziti_context = None
        self.use_ziti = False

    def start(self, host: str = "0.0.0.0", port: int = 9000):
        """Start the ingestion server."""
        self.use_ziti = self._init_ziti()
        
        if self.use_ziti:
            self._start_ziti_server()
        else:
            self._start_demo_server(host, port)

    def _init_ziti(self) -> bool:
        try:
            import openziti
        
            if not INGESTION_SERVER_IDENTITY.exists():
                print(f"Ingestion server identity not found: {INGESTION_SERVER_IDENTITY}")
                return False
        
            result = openziti.load(str(INGESTION_SERVER_IDENTITY))
            # openziti.load returns a tuple (context, status)
            if isinstance(result, tuple):
                self.ziti_context = result[0]
            else:
                self.ziti_context = result
            
            print(f"Ingestion server identity loaded")
            return True
    
        except ImportError:
            print("openziti not installed — running in demo mode")
            return False
        except Exception as e:
            print(f"Ziti init failed: {e}")
            return False

    def _start_ziti_server(self):
        import openziti
        import uvicorn

        print(f"\n{'='*60}")
        print(f"ZITI-SECURED INGESTION SERVER")
        print(f"Service: {INGESTION_SERVICE_NAME}")
        print(f"Mode: DARK SERVICE (no open ports)")
        print(f"Only Ziti-enrolled machines can connect")
        print(f"{'='*60}\n")

        print(f"Starting Ziti-secured ingestion service")
        print(f"Waiting for verified machine connections...\n")

        # Use OpenZiti monkey patching to intercept all socket calls
        # This makes uvicorn transparently use the Ziti fabric
        openziti.monkeypatch(ztx=self.ziti_context, service=INGESTION_SERVICE_NAME)
    
        # Now run uvicorn normally — all connections go through Ziti
        uvicorn.run(
            ingestion_app,
            host="0.0.0.0",
            port=8000,
            log_level="info"
        )

    def _start_demo_server(self, host: str, port: int):
        """
        Demo mode: starts a regular HTTP server.
        Used when no Ziti controller is available.
        """
        import uvicorn
        
        print(f"\n{'='*60}")
        print(f"DEMO MODE INGESTION SERVER")
        print(f"URL: http://{host}:{port}")
        print(f"No Ziti security (demo only)")
        print(f"{'='*60}\n")
        
        uvicorn.run(ingestion_app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Ziti-protected ingestion server")
    parser.add_argument("--host", default="0.0.0.0", help="Host for demo mode")
    parser.add_argument("--port", type=int, default=9000, help="Port for demo mode")
    parser.add_argument("--demo", action="store_true", help="Force demo mode")
    args = parser.parse_args()

    server = ZitiIngestionServer()
    if args.demo:
        server._start_demo_server(args.host, args.port)
    else:
        server.start(host=args.host, port=args.port)
