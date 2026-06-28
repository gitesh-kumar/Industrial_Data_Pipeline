# Zero-Trust Security Layer — OpenZiti Integration

## Why This Exists

Industrial sensor data is a high-value target. A single compromised SCADA terminal can inject false readings like fake vibration spikes, manipulated temperature data, causing either unnecessary shutdowns or, worse, masking real failures. This is called **data poisoning** and it's a documented threat in OT/ICS environments.

Traditional security puts a firewall around the factory network and trusts everything inside. Zero-trust assumes the network is already compromised and verifies every connection, every time.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    OT Layer (Factory Floor)                   │
│                                                               │
│  TURBINE_01 [turbine_01.json] ──┐                            │
│  TURBINE_02 [turbine_02.json] ──┤                            │
│  PUMP_01    [pump_01.json]    ──┤                            │
│  ...17 machines, each with      │                            │
│     unique X.509 certificate    │                            │
└─────────────────────────────────┼────────────────────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │      OpenZiti Fabric         │
                    │                              │
                    │  • Mutual TLS                │
                    │  • Identity verification     │
                    │  • No open ports             │
                    │  • Policy enforcement        │
                    │  • Audit logging             │
                    └─────────────┬────────────────┘
                                  │
┌─────────────────────────────────┼────────────────────────────┐
│                    IT Layer (Data Pipeline)                    │
│                                 │                             │
│              ┌──────────────────▼──────────────────┐         │
│              │   Ingestion Server (dark service)     │         │
│              │   No open ports — Ziti only           │         │
│              └──────────────────┬──────────────────┘         │
│                                 │                             │
│              Bronze → Silver → Gold → FastAPI → Dashboard     │
└─────────────────────────────────────────────────────────────┘
```

---

## Security Properties

**Every machine has a unique cryptographic identity**
Each of the 17 machines holds an X.509 certificate stored as a JSON identity file. This certificate is issued by the Ziti controller's PKI. No certificate = no connection.

**Mutual TLS on every connection**
Both the machine and the ingestion server verify each other's identity. A machine can't impersonate the server. The server can't be substituted with a rogue endpoint.

**No open ports**
The ingestion server binds to the Ziti fabric as a "dark service". It has no listening TCP ports. A port scanner sees nothing. There is no attack surface.

**Granular revocation**
If COMPRESSOR_02 is compromised, you delete its identity from the controller. It immediately loses access. The other 16 machines are unaffected. This is the core advantage over IP-based allowlists.

**Audit trail**
Every connection is logged with the machine's identity, timestamp, and status. This creates a cryptographically-verifiable audit trail for compliance.

---

## File Structure

```
ziti/
├── config.py            — controller URL, machine list, service names
├── enroll_machines.py   — generates X.509 identity for each machine
├── machine_client.py    — Ziti-aware machine simulator (replaces ingestion.py)
├── ingestion_server.py  — dark service, receives only Ziti-verified data
├── policies.py          — zero-trust access control policy definitions
├── identities/          — machine identity JSON files (gitignored)
│   ├── turbine_01.json
│   ├── pump_01.json
│   └── ...
└── README.md            — this file
```

---

## Setup (Requires Hetzner Server)

### Step 1 — Deploy Ziti Controller on Hetzner

```bash
# SSH into your Hetzner server
ssh root@your-hetzner-ip

# Download and run Ziti express install
curl -sL https://get.openziti.io/quick/ziti-cli-functions.sh | bash
expressInstall
```

### Step 2 — Update Configuration

Edit `ziti/config.py`:
```python
ZITI_CONTROLLER_URL = "https://your-hetzner-ip:8441"
ZITI_ADMIN_PASSWORD = "your-secure-password"
```

### Step 3 — Apply Policies

```bash
python ziti/policies.py --apply
```

### Step 4 — Enroll All Machines

```bash
python ziti/enroll_machines.py --enroll-all
```

### Step 5 — Start Ingestion Server

```bash
python ziti/ingestion_server.py
```

### Step 6 — Start Machine Clients

```bash
python ziti/machine_client.py --all
```

---

## Demo Mode (No Ziti Controller)

All scripts fall back to demo mode when no Ziti controller is available. Identity files are created as mock JSON, and data flows through direct HTTP instead of the Ziti fabric. The code architecture is identical — only the transport layer changes.

```bash
# Run in demo mode (no Hetzner server needed)
python ziti/enroll_machines.py --enroll-all  # creates mock identities
python ziti/machine_client.py --all           # streams data in demo mode
```

---

## Zero-Trust Policy Summary

| Who | Can Do | What |
|---|---|---|
| `#factory-device` identities | Dial (send) | `factory-ingestion-service` |
| `#ingestion-service` identity | Bind (receive) | `factory-ingestion-service` |
| Everything else | ❌ DENIED | Everything |

Default deny. Explicit allow. Every connection verified. This is zero-trust.

---

## Threat Model

| Threat | Traditional | With OpenZiti |
|---|---|---|
| Rogue device on factory network | ✅ Can send data | ❌ No identity = no access |
| Compromised machine | ✅ Continues sending | ❌ Revoke identity instantly |
| Network interception | ⚠️ Data exposed | ❌ End-to-end encrypted |
| Port scanning | ✅ Finds open ports | ❌ No ports to find |
| Lateral movement | ✅ Access spreads | ❌ Per-service policies |
| Insider threat | ⚠️ Hard to audit | ✅ Full audit trail |

---

## CV / Interview Notes

This implementation demonstrates:

- **OT/IT convergence** — bridging factory floor devices with enterprise IT infrastructure securely
- **Application-embedded zero-trust** — security at the application layer, not just the network perimeter
- **Cryptographic identity management** — X.509 PKI for device authentication
- **Dark services** — eliminating attack surface by removing open ports entirely
- **Granular revocation** — per-device access control without network reconfiguration
- **Audit compliance** — cryptographically-verifiable connection logs

Relevant to roles at: Siemens, Bosch, ABB, Honeywell, Schneider Electric, and any company working on Industry 4.0 / IIoT security.
