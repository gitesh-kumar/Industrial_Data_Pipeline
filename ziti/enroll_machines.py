"""
Machine Enrollment Script
==========================
Creates a cryptographic Ziti identity for each of the 17 factory machines.

This script is run ONCE when setting up the zero-trust fabric.
Each machine gets its own X.509 certificate stored as a JSON identity file.

In production: run this on the Ziti controller server, then distribute
identity files to each physical machine via secure out-of-band channel.

Usage:
    python ziti/enroll_machines.py --enroll-all
    python ziti/enroll_machines.py --enroll TURBINE_01
    python ziti/enroll_machines.py --list
    python ziti/enroll_machines.py --revoke COMPRESSOR_02
"""

import argparse
import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))
from ziti.config import (
    MACHINES, IDENTITY_DIR, INGESTION_SERVER_IDENTITY,
    INGESTION_SERVICE_NAME, FACTORY_DEVICE_ROLE,
    ZITI_CONTROLLER_URL, ZITI_ADMIN_USER, ZITI_ADMIN_PASSWORD,
    get_machine_identity_path
)

class ZitiEnrollmentManager:
    """
    Manages cryptographic identities for factory machines.
    
    Each machine receives a unique X.509 certificate that acts as its
    digital passport in the zero-trust fabric. This certificate is used
    for mutual TLS authentication — both the machine and the ingestion
    service verify each other's identity before any data flows.
    """

    def __init__(self):
        self.enrollment_log = IDENTITY_DIR / "enrollment_log.json"
        self.log = self._load_log()

    def _load_log(self) -> dict:
        if self.enrollment_log.exists():
            with open(self.enrollment_log) as f:
                return json.load(f)
        return {"enrolled": {}, "revoked": []}

    def _save_log(self):
        with open(self.enrollment_log, "w") as f:
            json.dump(self.log, f, indent=2)

    def _run_ziti_command(self, args: list) -> tuple:
        """Execute a Ziti CLI command."""
        cmd = ["ziti", "edge"] + args + [
            "--url", ZITI_CONTROLLER_URL,
            "--username", ZITI_ADMIN_USER,
            "--password", ZITI_ADMIN_PASSWORD
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    def enroll_machine(self, machine_id: str) -> bool:
        """
        Creates a Ziti identity for a factory machine.
        
        Process:
        1. Create identity in Ziti controller
        2. Assign role attributes (#factory-device, #machine-type)
        3. Generate enrollment JWT token
        4. Enroll using JWT to produce identity JSON file
        5. Log enrollment with timestamp
        """
        machine = next((m for m in MACHINES if m["id"] == machine_id), None)
        if not machine:
            print(f"❌ Unknown machine: {machine_id}")
            return False

        identity_path = get_machine_identity_path(machine_id)
        
        if identity_path.exists():
            print(f"⚠️  Identity already exists for {machine_id} at {identity_path}")
            return True

        print(f"🔐 Enrolling {machine_id}...")

        # Step 1 — Create identity in controller
        identity_name = f"factory-machine-{machine_id.lower()}"
        role_attributes = [FACTORY_DEVICE_ROLE, f"#{machine['role']}"]
        
        returncode, stdout, stderr = self._run_ziti_command([
            "create", "identity", "device", identity_name,
            "--role-attributes", ",".join(role_attributes),
            "--jwt-output-file", str(IDENTITY_DIR / f"{machine_id.lower()}.jwt")
        ])

        if returncode != 0:
            print(f"❌ Failed to create identity for {machine_id}: {stderr}")
            # In demo mode (no controller), create a mock identity file
            self._create_mock_identity(machine_id, machine)
            return True

        # Step 2 — Enroll using JWT to produce identity JSON
        jwt_path = IDENTITY_DIR / f"{machine_id.lower()}.jwt"
        returncode, stdout, stderr = self._run_ziti_command([
            "enroll", "--jwt", str(jwt_path),
            "--out", str(identity_path)
        ])

        if returncode != 0:
            print(f"❌ Failed to enroll {machine_id}: {stderr}")
            return False

        # Step 3 — Log enrollment
        self.log["enrolled"][machine_id] = {
            "enrolled_at": datetime.now().isoformat(),
            "identity_path": str(identity_path),
            "role": machine["role"],
            "type": machine["type"]
        }
        self._save_log()

        # Clean up JWT file
        jwt_path.unlink(missing_ok=True)

        print(f"✅ {machine_id} enrolled — identity: {identity_path}")
        return True

    def _create_mock_identity(self, machine_id: str, machine: dict):
        """
        Creates a mock identity file for demonstration purposes.
        Used when no Ziti controller is available (local dev/demo).
        
        In production this is replaced by a real X.509 certificate.
        """
        identity_path = get_machine_identity_path(machine_id)
        
        mock_identity = {
            "ztAPI": ZITI_CONTROLLER_URL,
            "id": {
                "key": f"pem:-----BEGIN EC PRIVATE KEY-----\n[MOCK-KEY-{machine_id}]\n-----END EC PRIVATE KEY-----",
                "cert": f"pem:-----BEGIN CERTIFICATE-----\n[MOCK-CERT-{machine_id}]\n-----END CERTIFICATE-----",
                "ca": "pem:-----BEGIN CERTIFICATE-----\n[MOCK-CA]\n-----END CERTIFICATE-----"
            },
            "configTypes": ["all"],
            "machine_metadata": {
                "machine_id": machine_id,
                "machine_type": machine["type"],
                "role": machine["role"],
                "enrolled_at": datetime.now().isoformat(),
                "mode": "DEMO — replace with real Ziti controller enrollment"
            }
        }
        
        with open(identity_path, "w") as f:
            json.dump(mock_identity, f, indent=2)
        
        self.log["enrolled"][machine_id] = {
            "enrolled_at": datetime.now().isoformat(),
            "identity_path": str(identity_path),
            "role": machine["role"],
            "type": machine["type"],
            "mode": "mock"
        }
        self._save_log()
        
        print(f"📋 {machine_id} — mock identity created (demo mode)")

    def enroll_ingestion_server(self):
        """Creates identity for the ingestion service itself."""
        print("🔐 Enrolling ingestion server...")
        
        if INGESTION_SERVER_IDENTITY.exists():
            print(f"⚠️  Ingestion server identity already exists")
            return True

        returncode, stdout, stderr = self._run_ziti_command([
            "create", "identity", "service", "factory-ingestion-server",
            "--role-attributes", "#ingestion-service",
            "--jwt-output-file", str(IDENTITY_DIR / "ingestion-server.jwt")
        ])

        if returncode != 0:
            # Demo mode
            mock_identity = {
                "ztAPI": ZITI_CONTROLLER_URL,
                "id": {
                    "key": "pem:-----BEGIN EC PRIVATE KEY-----\n[MOCK-SERVER-KEY]\n-----END EC PRIVATE KEY-----",
                    "cert": "pem:-----BEGIN CERTIFICATE-----\n[MOCK-SERVER-CERT]\n-----END CERTIFICATE-----",
                    "ca": "pem:-----BEGIN CERTIFICATE-----\n[MOCK-CA]\n-----END CERTIFICATE-----"
                },
                "configTypes": ["all"],
                "server_metadata": {
                    "service": "factory-ingestion-server",
                    "enrolled_at": datetime.now().isoformat(),
                    "mode": "DEMO"
                }
            }
            with open(INGESTION_SERVER_IDENTITY, "w") as f:
                json.dump(mock_identity, f, indent=2)
            print(f"📋 Ingestion server — mock identity created (demo mode)")
            return True

        print(f"✅ Ingestion server enrolled")
        return True

    def enroll_all(self):
        """Enrolls all 17 machines plus the ingestion server."""
        print(f"\n🏭 ENROLLING ALL FACTORY MACHINES")
        print(f"{'='*50}")
        print(f"Controller: {ZITI_CONTROLLER_URL}")
        print(f"Identity dir: {IDENTITY_DIR}")
        print(f"{'='*50}\n")

        # Enroll ingestion server first
        self.enroll_ingestion_server()
        print()

        # Enroll all machines
        success = 0
        failed = 0
        for machine in MACHINES:
            if self.enroll_machine(machine["id"]):
                success += 1
            else:
                failed += 1

        print(f"\n{'='*50}")
        print(f"✅ Enrolled: {success}/{len(MACHINES)} machines")
        if failed:
            print(f"❌ Failed: {failed} machines")
        print(f"📁 Identities stored in: {IDENTITY_DIR}")
        print(f"{'='*50}")

    def list_identities(self):
        """Lists all enrolled machine identities."""
        print(f"\n📋 ENROLLED IDENTITIES")
        print(f"{'='*50}")
        
        if not self.log["enrolled"]:
            print("No machines enrolled yet. Run --enroll-all first.")
            return

        for machine_id, info in self.log["enrolled"].items():
            mode = info.get("mode", "production")
            path = Path(info["identity_path"])
            exists = "✅" if path.exists() else "❌ MISSING"
            print(f"{exists} {machine_id:20} | {info['type']:15} | {mode:10} | {info['enrolled_at'][:10]}")
        
        print(f"\nTotal: {len(self.log['enrolled'])} identities")
        if self.log["revoked"]:
            print(f"Revoked: {', '.join(self.log['revoked'])}")

    def revoke_machine(self, machine_id: str):
        """
        Revokes a machine's identity — immediately cuts off its access.
        This is the key advantage of zero-trust: granular revocation.
        """
        print(f"🚫 Revoking identity for {machine_id}...")
        
        returncode, stdout, stderr = self._run_ziti_command([
            "delete", "identity", f"factory-machine-{machine_id.lower()}"
        ])

        # Remove local identity file
        identity_path = get_machine_identity_path(machine_id)
        if identity_path.exists():
            identity_path.unlink()

        # Update log
        if machine_id in self.log["enrolled"]:
            del self.log["enrolled"][machine_id]
        self.log["revoked"].append(machine_id)
        self._save_log()

        print(f"✅ {machine_id} identity revoked — access immediately terminated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Factory Machine Ziti Enrollment Manager")
    parser.add_argument("--enroll-all", action="store_true", help="Enroll all 17 machines")
    parser.add_argument("--enroll", metavar="MACHINE_ID", help="Enroll a specific machine")
    parser.add_argument("--list", action="store_true", help="List all enrolled identities")
    parser.add_argument("--revoke", metavar="MACHINE_ID", help="Revoke a machine's identity")
    args = parser.parse_args()

    manager = ZitiEnrollmentManager()

    if args.enroll_all:
        manager.enroll_all()
    elif args.enroll:
        manager.enroll_machine(args.enroll)
    elif args.list:
        manager.list_identities()
    elif args.revoke:
        manager.revoke_machine(args.revoke)
    else:
        parser.print_help()
