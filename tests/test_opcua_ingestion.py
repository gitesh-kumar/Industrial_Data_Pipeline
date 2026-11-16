"""The bronze CSV written through OPC UA must equal what the simulator produced, column for column."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("asyncua")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import ingestion  # noqa: E402


def test_bronze_csv_through_opcua_matches_the_simulator(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ingestion, "OPCUA_URL", "opc.tcp://127.0.0.1:4871/factory")

    np.random.seed(11)
    expected = pd.concat([ingestion.SmartFactorySimulator().generate_batch() for _ in range(2)])
    expected = expected.drop(columns="timestamp").reset_index(drop=True)

    np.random.seed(11)
    ingestion.SmartFactorySimulator().run(cycles=2, interval=0.1)

    got = pd.read_csv("data/bronze_sensors.csv")
    assert list(got.columns) == ingestion.COLUMNS
    assert len(got) == 34 and got["machine_id"].nunique() == 17
    assert got.drop(columns="timestamp").reset_index(drop=True).equals(expected)
