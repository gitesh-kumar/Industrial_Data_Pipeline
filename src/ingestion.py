"""
Bronze layer: machine readings -> OPC UA -> CSV.

The 17 simulated machines are published by an OPC UA server as nodes
(Objects / Factory / <machine> / Vibration, Temperature, PowerUsage, FailureSpike, Degradation).
An OPC UA client subscribes to those nodes, and the bronze CSV is written from what the
client received. So the pipeline reads the machines the way it would read a real plant,
through OPC UA, and not straight from the simulator.

While this runs you can browse the nodes with any OPC UA client at
opc.tcp://127.0.0.1:4840/factory (change it with the OPCUA_URL variable).

Honest limits: server and client run in this one process on the same computer, and
the server uses no encryption. A real plant would use signed and encrypted sessions
with certificates. The CSV format is the same as before, so the next steps do not change.
"""
import asyncio
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd

OPCUA_URL = os.getenv("OPCUA_URL", "opc.tcp://127.0.0.1:4840/factory")
NAMESPACE = "urn:industrial-factory:simulated"
# OPC UA variable name -> column in the bronze CSV
VARIABLES = {
    "Vibration": "vibration_rms",
    "Temperature": "temp_c",
    "PowerUsage": "power_kw",
    "FailureSpike": "failure_spike",
    "Degradation": "degradation",
}
COLUMNS = ["timestamp", "machine_id", "machine_type", "vibration_rms", "temp_c", "power_kw",
           "failure_spike", "degradation"]


class SmartFactorySimulator:
    def __init__(self):
        self.machines = [
            # Turbines
            'TURBINE_01', 'TURBINE_02', 'TURBINE_03',
            # Pumps
            'PUMP_01', 'PUMP_02', 'PUMP_03', 'PUMP_04',
            # Compressors
            'COMPRESSOR_01', 'COMPRESSOR_02', 'COMPRESSOR_03',
            # Heat Exchangers
            'HEAT_EXCHANGER_01', 'HEAT_EXCHANGER_02',
            # Motors
            'MOTOR_01', 'MOTOR_02', 'MOTOR_03',
            # Generators
            'GENERATOR_01', 'GENERATOR_02'
        ]

        # Each machine type has different normal operating ranges
        self.machine_profiles = {
            'TURBINE':        {'vibration': (2.0, 4.0), 'temp': (60, 80),  'power': (45, 60)},
            'PUMP':           {'vibration': (1.0, 3.0), 'temp': (35, 55),  'power': (10, 20)},
            'COMPRESSOR':     {'vibration': (3.0, 5.0), 'temp': (70, 90),  'power': (30, 45)},
            'HEAT_EXCHANGER': {'vibration': (0.5, 1.5), 'temp': (90, 120), 'power': (5,  10)},
            'MOTOR':          {'vibration': (1.5, 3.5), 'temp': (45, 65),  'power': (20, 35)},
            'GENERATOR':      {'vibration': (2.5, 4.5), 'temp': (55, 75),  'power': (80, 120)},
        }

        self.data_path = 'data/bronze_sensors.csv'
        if not os.path.exists('data'):
            os.makedirs('data')

    def get_profile(self, machine_id):
        for key in self.machine_profiles:
            if key in machine_id:
                return self.machine_profiles[key]
        return self.machine_profiles['MOTOR']

    def generate_batch(self):
        records = []
        for machine_id in self.machines:
            profile = self.get_profile(machine_id)

            base_vibration = np.random.uniform(*profile['vibration'])

            # 5% chance of failure spike
            failure_spike = np.random.rand() > 0.95
            if failure_spike:
                base_vibration *= np.random.uniform(2.5, 4.0)

            # 3% chance of gradual degradation (vibration slowly increasing)
            degradation = np.random.rand() > 0.97
            if degradation:
                base_vibration *= np.random.uniform(1.5, 2.0)

            temp = profile['temp'][0] + (base_vibration * 3) + np.random.normal(0, 3)

            # Power spikes during high vibration
            power_multiplier = 1.3 if failure_spike else 1.0
            power = np.random.uniform(*profile['power']) * power_multiplier

            records.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'machine_id': machine_id,
                'machine_type': machine_id.rsplit('_', 1)[0],
                'vibration_rms': round(base_vibration, 4),
                'temp_c': round(temp, 2),
                'power_kw': round(power, 2),
                'failure_spike': failure_spike,
                'degradation': degradation
            })
        return pd.DataFrame(records)

    # ── OPC UA ──────────────────────────────────────────────────────────
    async def _publish_machines(self, server, index):
        """Create Objects / Factory / <machine> / <variable> and return the node of every variable."""
        from asyncua import ua
        factory = await server.nodes.objects.add_object(ua.NodeId("Factory", index), ua.QualifiedName("Factory", index))
        nodes = {}
        for machine in self.machines:
            obj = await factory.add_object(ua.NodeId(machine, index), ua.QualifiedName(machine, index))
            for name in VARIABLES:
                is_flag = name in ("FailureSpike", "Degradation")
                nodes[(machine, name)] = await obj.add_variable(
                    ua.NodeId(f"{machine}.{name}", index), ua.QualifiedName(name, index),
                    False if is_flag else 0.0,
                    ua.VariantType.Boolean if is_flag else ua.VariantType.Double)
        return nodes

    async def _serve(self, cycles=None, interval=3.0):
        from asyncua import Client, Server, ua

        server = Server()
        await server.init()
        server.set_endpoint(OPCUA_URL)
        server.set_server_name("Industrial factory (simulated)")
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        index = await server.register_namespace(NAMESPACE)
        server_nodes = await self._publish_machines(server, index)

        latest = {}                                   # (machine, variable) -> last value the client received
        names = {}                                    # node id text -> (machine, variable)

        class Receiver:                               # called by the client library for every change
            def datachange_notification(self, node, value, data):
                key = names.get(node.nodeid.to_string())
                if key:
                    latest[key] = value

        async with server:
            async with Client(OPCUA_URL) as client:
                index = await client.get_namespace_index(NAMESPACE)
                client_nodes = {}
                for machine in self.machines:
                    for name in VARIABLES:
                        node = client.get_node(ua.NodeId(f"{machine}.{name}", index))
                        client_nodes[(machine, name)] = node
                        names[node.nodeid.to_string()] = (machine, name)
                subscription = await client.create_subscription(200, Receiver())
                await subscription.subscribe_data_change(list(client_nodes.values()))

                print(f"🚀 Ingestion started. Monitoring {len(self.machines)} machines over OPC UA at {OPCUA_URL}")
                done = 0
                while cycles is None or done < cycles:
                    batch = self.generate_batch()
                    wanted = {}
                    for rec in batch.to_dict("records"):          # the machines write their values
                        for name, column in VARIABLES.items():
                            value = rec[column]
                            value = bool(value) if name in ("FailureSpike", "Degradation") else float(value)
                            wanted[(rec["machine_id"], name)] = value
                            await server_nodes[(rec["machine_id"], name)].write_value(
                                ua.Variant(value, ua.VariantType.Boolean if isinstance(value, bool)
                                           else ua.VariantType.Double))

                    deadline = time.monotonic() + 2.0               # wait until the client has every new value
                    while time.monotonic() < deadline and any(latest.get(k) != v for k, v in wanted.items()):
                        await asyncio.sleep(0.05)
                    if any(latest.get(k) != v for k, v in wanted.items()):
                        print("⚠️ The OPC UA client did not receive every value in time, using the last values it has.")

                    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    rows = [{"timestamp": stamp, "machine_id": m, "machine_type": m.rsplit('_', 1)[0],
                             **{col: latest.get((m, name)) for name, col in VARIABLES.items()}}
                            for m in self.machines]
                    df = pd.DataFrame(rows, columns=COLUMNS)
                    file_exists = os.path.exists(self.data_path)
                    df.to_csv(self.data_path, mode='a', header=not file_exists, index=False)
                    print(f"✅ Batch written — {len(df)} records at {datetime.now().strftime('%H:%M:%S')}")
                    done += 1
                    await asyncio.sleep(interval)

    def run(self, cycles=None, interval=3.0):
        asyncio.run(self._serve(cycles, interval))

if __name__ == "__main__":
    sim = SmartFactorySimulator()
    sim.run()
