"""
OpenZiti Configuration
======================
Central configuration for the zero-trust network fabric.
All machine identities, service names and controller settings live here.

Set these via environment variables (.env file) — never hardcode
real credentials or IP addresses in this file.
"""

import os
from pathlib import Path

# ── CONTROLLER ───────────────────────────────────────────────────
# Set these in your .env file:
#   ZITI_CONTROLLER_URL=https://your-server-ip:1280
#   ZITI_ADMIN_PASSWORD=your-actual-password
ZITI_CONTROLLER_URL = os.getenv("ZITI_CONTROLLER_URL", "https://localhost:1280")
ZITI_CONTROLLER_MGMT_URL = os.getenv("ZITI_CONTROLLER_MGMT_URL", "https://localhost:1280")

# Admin credentials for the Ziti controller
ZITI_ADMIN_USER = os.getenv("ZITI_ADMIN_USER", "admin")
ZITI_ADMIN_PASSWORD = os.getenv("ZITI_ADMIN_PASSWORD", "")

# ── SERVICE NAMES ────────────────────────────────────────────────
INGESTION_SERVICE_NAME = "factory-ingestion-service"

# ── IDENTITY PATHS ───────────────────────────────────────────────
IDENTITY_DIR = Path(__file__).parent / "identities"
IDENTITY_DIR.mkdir(exist_ok=True)
ZITI_CA_CERT = str(IDENTITY_DIR / "ca.cert")
INGESTION_SERVER_IDENTITY = IDENTITY_DIR / "ingestion-server.json"

# ── MACHINE DEFINITIONS ──────────────────────────────────────────
MACHINES = [
    {"id": "TURBINE_01",        "type": "TURBINE",        "role": "turbine-devices"},
    {"id": "TURBINE_02",        "type": "TURBINE",        "role": "turbine-devices"},
    {"id": "TURBINE_03",        "type": "TURBINE",        "role": "turbine-devices"},
    {"id": "PUMP_01",           "type": "PUMP",           "role": "pump-devices"},
    {"id": "PUMP_02",           "type": "PUMP",           "role": "pump-devices"},
    {"id": "PUMP_03",           "type": "PUMP",           "role": "pump-devices"},
    {"id": "PUMP_04",           "type": "PUMP",           "role": "pump-devices"},
    {"id": "COMPRESSOR_01",     "type": "COMPRESSOR",     "role": "compressor-devices"},
    {"id": "COMPRESSOR_02",     "type": "COMPRESSOR",     "role": "compressor-devices"},
    {"id": "COMPRESSOR_03",     "type": "COMPRESSOR",     "role": "compressor-devices"},
    {"id": "HEAT_EXCHANGER_01", "type": "HEAT_EXCHANGER", "role": "heat-exchanger-devices"},
    {"id": "HEAT_EXCHANGER_02", "type": "HEAT_EXCHANGER", "role": "heat-exchanger-devices"},
    {"id": "MOTOR_01",          "type": "MOTOR",          "role": "motor-devices"},
    {"id": "MOTOR_02",          "type": "MOTOR",          "role": "motor-devices"},
    {"id": "MOTOR_03",          "type": "MOTOR",          "role": "motor-devices"},
    {"id": "GENERATOR_01",      "type": "GENERATOR",      "role": "generator-devices"},
    {"id": "GENERATOR_02",      "type": "GENERATOR",      "role": "generator-devices"},
]

# ── ZERO TRUST POLICIES ──────────────────────────────────────────
FACTORY_DEVICE_ROLE = "#factory-device"
INGESTION_SERVICE_ROLE = "#ingestion-service"

# ── HELPERS ──────────────────────────────────────────────────────
def get_machine_identity_path(machine_id: str) -> Path:
    return IDENTITY_DIR / f"{machine_id.lower()}.json"

def get_machine_by_id(machine_id: str) -> dict:
    return next((m for m in MACHINES if m["id"] == machine_id), None)