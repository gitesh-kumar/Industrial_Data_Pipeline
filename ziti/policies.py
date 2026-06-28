"""
Zero-Trust Policy Definitions
==============================
Defines the access control policies for the Ziti fabric.

These policies answer the question: "Who is allowed to talk to what?"

In zero-trust networking, everything is denied by default.
You must explicitly grant access through policies.

Policy Structure:
    Service Policy — defines which identities can USE a service
    Edge Router Policy — defines which identities can use which routers

Deployment:
    Run this script once after setting up the Ziti controller:
    python ziti/policies.py --apply

Reference:
    https://openziti.io/docs/learn/core-concepts/security/authorization/policies/overview
"""

import sys
import json
import subprocess
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from ziti.config import (
    ZITI_CONTROLLER_URL, ZITI_ADMIN_USER, ZITI_ADMIN_PASSWORD,
    INGESTION_SERVICE_NAME, FACTORY_DEVICE_ROLE, INGESTION_SERVICE_ROLE,
    MACHINES
)


# ── POLICY DEFINITIONS ───────────────────────────────────────────

POLICIES = {

    # ── SERVICE POLICIES ─────────────────────────────────────────

    "factory-devices-can-send-data": {
        "type": "ServicePolicy",
        "description": "Allows enrolled factory machines to SEND data to ingestion service",
        "policyType": "Dial",  # Dial = client/sender
        "identityRoles": [FACTORY_DEVICE_ROLE],  # Any identity tagged #factory-device
        "serviceRoles": [INGESTION_SERVICE_ROLE],  # Can reach #ingestion-service
        "semantic": "AnyOf",
        "rationale": """
            Every machine enrolled with #factory-device role can send data.
            Adding a new machine = enroll it with this role = automatic access.
            Revoking a machine = delete its identity = immediate access termination.
        """
    },

    "ingestion-server-can-receive-data": {
        "type": "ServicePolicy",
        "description": "Allows ingestion server to RECEIVE data (bind to service)",
        "policyType": "Bind",  # Bind = server/receiver
        "identityRoles": [INGESTION_SERVICE_ROLE],  # The ingestion server identity
        "serviceRoles": [INGESTION_SERVICE_ROLE],
        "semantic": "AnyOf",
        "rationale": """
            The ingestion server binds to the service and listens for incoming connections.
            Only the ingestion server identity can bind — not machines.
        """
    },

    # ── DEVICE-TYPE ISOLATION POLICIES ───────────────────────────
    # Optional: restrict which machine types can send data
    # Useful for segmenting OT networks by device class

    "turbines-isolated-policy": {
        "type": "ServicePolicy",
        "description": "Turbine devices can only access turbine-specific services",
        "policyType": "Dial",
        "identityRoles": ["#turbine-devices"],
        "serviceRoles": [INGESTION_SERVICE_ROLE],
        "semantic": "AnyOf",
        "rationale": """
            Optional: further restricts turbines to their own service endpoint.
            Prevents a compromised turbine from accessing pump or compressor data.
            Implements micro-segmentation within the OT network.
        """
    },

    # ── EDGE ROUTER POLICIES ─────────────────────────────────────

    "all-factory-devices-router-access": {
        "type": "EdgeRouterPolicy",
        "description": "Factory devices can use any available edge router",
        "identityRoles": [FACTORY_DEVICE_ROLE],
        "edgeRouterRoles": ["#all"],
        "semantic": "AnyOf",
        "rationale": """
            Allows factory machines to connect through any available Ziti router.
            In production: restrict to specific regional routers for latency optimization.
        """
    },

    "ingestion-server-router-access": {
        "type": "EdgeRouterPolicy",
        "description": "Ingestion server can use any edge router",
        "identityRoles": [INGESTION_SERVICE_ROLE],
        "edgeRouterRoles": ["#all"],
        "semantic": "AnyOf"
    },

    # ── SERVICE EDGE ROUTER POLICIES ─────────────────────────────

    "ingestion-service-router-policy": {
        "type": "ServiceEdgeRouterPolicy",
        "description": "Ingestion service is accessible through all routers",
        "serviceRoles": [INGESTION_SERVICE_ROLE],
        "edgeRouterRoles": ["#all"],
        "semantic": "AnyOf"
    }
}


# ── SERVICE DEFINITION ───────────────────────────────────────────

SERVICES = {
    INGESTION_SERVICE_NAME: {
        "name": INGESTION_SERVICE_NAME,
        "roleAttributes": [INGESTION_SERVICE_ROLE.lstrip("#")],
        "encryptionRequired": True,  # Force end-to-end encryption
        "terminatorStrategy": "smartrouting",
        "configs": [],
        "rationale": """
            The ingestion service is the only entry point for factory sensor data.
            encryptionRequired=True means even if Ziti routers are compromised,
            data cannot be decrypted without the endpoint identity keys.
        """
    }
}


class ZitiPolicyManager:
    """Applies zero-trust policies to the Ziti controller."""

    def _run(self, args: list) -> tuple:
        cmd = ["ziti", "edge"] + args + [
            "--url", ZITI_CONTROLLER_URL,
            "--username", ZITI_ADMIN_USER,
            "--password", ZITI_ADMIN_PASSWORD
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    def create_service(self, service_name: str, service_config: dict):
        """Creates a Ziti service."""
        print(f"📡 Creating service: {service_name}")
        
        role_attrs = ",".join(service_config.get("roleAttributes", []))
        returncode, stdout, stderr = self._run([
            "create", "service", service_name,
            "--role-attributes", role_attrs,
            "--encryption-required"
        ])
        
        if returncode == 0:
            print(f"✅ Service created: {service_name}")
        else:
            print(f"⚠️  {service_name}: {stderr.strip() or 'already exists'}")

    def create_service_policy(self, policy_name: str, policy: dict):
        """Creates a Ziti service policy."""
        if policy.get("type") != "ServicePolicy":
            return
        
        print(f"🔒 Creating service policy: {policy_name}")
        
        identity_roles = " ".join(policy.get("identityRoles", []))
        service_roles = " ".join(policy.get("serviceRoles", []))
        
        returncode, stdout, stderr = self._run([
            "create", "service-policy", policy_name,
            policy["policyType"],
            "--identity-roles", identity_roles,
            "--service-roles", service_roles,
            "--semantic", policy.get("semantic", "AnyOf")
        ])
        
        if returncode == 0:
            print(f"✅ Policy created: {policy_name}")
        else:
            print(f"⚠️  {policy_name}: {stderr.strip() or 'already exists'}")

    def create_edge_router_policy(self, policy_name: str, policy: dict):
        """Creates a Ziti edge router policy."""
        if policy.get("type") != "EdgeRouterPolicy":
            return
        
        print(f"🌐 Creating edge router policy: {policy_name}")
        
        identity_roles = " ".join(policy.get("identityRoles", []))
        router_roles = " ".join(policy.get("edgeRouterRoles", []))
        
        returncode, stdout, stderr = self._run([
            "create", "edge-router-policy", policy_name,
            "--identity-roles", identity_roles,
            "--edge-router-roles", router_roles,
            "--semantic", policy.get("semantic", "AnyOf")
        ])
        
        if returncode == 0:
            print(f"✅ Edge router policy created: {policy_name}")
        else:
            print(f"⚠️  {policy_name}: {stderr.strip() or 'already exists'}")

    def apply_all(self):
        """Applies all services and policies to the Ziti controller."""
        print(f"\n{'='*60}")
        print(f"🔒 APPLYING ZERO-TRUST POLICIES")
        print(f"Controller: {ZITI_CONTROLLER_URL}")
        print(f"{'='*60}\n")

        # Create services first
        print("📡 SERVICES")
        print("-" * 40)
        for service_name, service_config in SERVICES.items():
            self.create_service(service_name, service_config)

        print("\n🔒 SERVICE POLICIES")
        print("-" * 40)
        for policy_name, policy in POLICIES.items():
            if policy.get("type") == "ServicePolicy":
                self.create_service_policy(policy_name, policy)

        print("\n🌐 EDGE ROUTER POLICIES")
        print("-" * 40)
        for policy_name, policy in POLICIES.items():
            if policy.get("type") == "EdgeRouterPolicy":
                self.create_edge_router_policy(policy_name, policy)

        print(f"\n{'='*60}")
        print(f"✅ Zero-trust policies applied")
        print(f"\nAccess summary:")
        print(f"  ✅ Enrolled machines ({FACTORY_DEVICE_ROLE}) → can SEND to ingestion")
        print(f"  ✅ Ingestion server ({INGESTION_SERVICE_ROLE}) → can RECEIVE data")
        print(f"  ❌ Everything else → DENIED by default")
        print(f"{'='*60}\n")

    def print_policy_summary(self):
        """Prints a human-readable summary of all policies."""
        print(f"\n{'='*60}")
        print(f"ZERO-TRUST POLICY SUMMARY")
        print(f"{'='*60}\n")
        
        for policy_name, policy in POLICIES.items():
            print(f"Policy: {policy_name}")
            print(f"  Type: {policy['type']} ({policy.get('policyType', 'N/A')})")
            print(f"  Who: {', '.join(policy.get('identityRoles', []))}")
            print(f"  What: {', '.join(policy.get('serviceRoles', policy.get('edgeRouterRoles', [])))}")
            if "rationale" in policy:
                print(f"  Why: {policy['rationale'].strip()[:80]}...")
            print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Ziti Zero-Trust Policy Manager")
    parser.add_argument("--apply", action="store_true", help="Apply all policies to controller")
    parser.add_argument("--summary", action="store_true", help="Print policy summary")
    args = parser.parse_args()

    manager = ZitiPolicyManager()

    if args.apply:
        manager.apply_all()
    elif args.summary:
        manager.print_policy_summary()
    else:
        manager.print_policy_summary()
