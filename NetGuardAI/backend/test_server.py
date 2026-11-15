import os
import sqlite3
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.server import (
    build_dashboard,
    counter_delta,
    get_available_port,
    initialize_database,
    store_snmp_observations,
    simulate_observation,
)
from backend.snmp_collector import (
    SnmpConfigurationError,
    load_credentials,
    load_devices,
)


class NetGuardBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.sqlite3"
        initialize_database(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_seed_dashboard_contains_demo_devices_and_safe_predictions(self) -> None:
        dashboard = build_dashboard(self.database_path)

        self.assertEqual(dashboard["mode"], "simulado")
        self.assertEqual(dashboard["summary"]["monitoredDevices"], 5)
        self.assertEqual(dashboard["summary"]["degradingDevices"], 2)
        self.assertGreaterEqual(dashboard["riskIndex"], 0)
        self.assertLessEqual(dashboard["riskIndex"], 100)
        self.assertTrue(dashboard["alerts"])
        predictions = [
            prediction
            for alert in dashboard["alerts"]
            for prediction in alert["predictions"]
        ]
        self.assertTrue(predictions)
        self.assertTrue(all(prediction["confidence"] < 0.5 for prediction in predictions))
        self.assertTrue(
            all("requiere evaluación" in prediction["reason"] for prediction in predictions)
        )

    def test_simulation_persists_metric_alert_and_topology_predictions(self) -> None:
        before = build_dashboard(self.database_path)
        result = simulate_observation(self.database_path)
        after = build_dashboard(self.database_path)

        self.assertEqual(after["summary"]["anomalies"], before["summary"]["anomalies"] + 1)
        self.assertEqual(after["alerts"][0]["id"], result["eventId"])
        self.assertEqual(after["alerts"][0]["device"], result["device"])
        self.assertGreaterEqual(result["confidence"], 0.65)
        self.assertTrue(after["alerts"][0]["predictions"])
        self.assertTrue(
            all(
                prediction["confidence"] < 0.5
                for prediction in after["alerts"][0]["predictions"]
            )
        )

    def test_initialization_completes_a_database_with_devices_but_no_metrics(self) -> None:
        partial_database = Path(self.temp_dir.name) / "partial.sqlite3"
        with sqlite3.connect(partial_database) as connection:
            connection.execute(
                """
                CREATE TABLE devices (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    ip TEXT NOT NULL UNIQUE,
                    type TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO devices (name, ip, type) VALUES (?, ?, ?)",
                ("PC-A", "192.168.1.15", "Computadora"),
            )

        initialize_database(partial_database)
        dashboard = build_dashboard(partial_database)
        result = simulate_observation(partial_database)
        after = build_dashboard(partial_database)

        self.assertEqual(dashboard["summary"]["monitoredDevices"], 5)
        self.assertTrue(dashboard["alerts"])
        self.assertEqual(after["alerts"][0]["id"], result["eventId"])
        self.assertEqual(
            after["summary"]["anomalies"], dashboard["summary"]["anomalies"] + 1
        )

    def test_available_port_skips_busy_ports(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        busy_port = listener.getsockname()[1]

        self.addCleanup(listener.close)
        self.assertIsInstance(get_available_port(busy_port), int)
        self.assertNotEqual(get_available_port(busy_port), busy_port)

    def test_snmp_configuration_accepts_only_two_private_lab_hosts(self) -> None:
        devices = load_devices(
            '[{"name":"Lenovo","ip":"192.168.1.48"},'
            '{"name":"Toshiba","ip":"192.168.1.45"}]'
        )
        self.assertEqual(len(devices), 2)

        with self.assertRaises(SnmpConfigurationError):
            load_devices(
                '[{"name":"public","ip":"8.8.8.8"},'
                '{"name":"Toshiba","ip":"192.168.1.45"}]'
            )

    def test_snmp_configuration_requires_private_auth_privacy_keys(self) -> None:
        values = {
            "SNMPV3_USERNAME": "netguard",
            "SNMPV3_AUTH_PASSWORD": "auth-passphrase",
            "SNMPV3_PRIV_PASSWORD": "privacy-passphrase",
            "SNMPV3_AUTH_PROTOCOL": "SHA",
            "SNMPV3_PRIV_PROTOCOL": "AES-128",
        }
        with patch.dict(os.environ, values, clear=True):
            credentials = load_credentials()
        self.assertEqual(credentials.auth_protocol, "SHA")
        self.assertEqual(credentials.privacy_protocol, "AES-128")

        with patch.dict(
            os.environ,
            {**values, "SNMPV3_AUTH_PASSWORD": "short"},
            clear=True,
        ):
            with self.assertRaises(SnmpConfigurationError):
                load_credentials()

    def test_snmp_observations_persist_and_calculate_interface_rates(self) -> None:
        observation = {
            "name": "Lenovo",
            "ip": "192.168.1.48",
            "type": "Computadora",
            "uptimeTicks": 1000,
            "uptimeSeconds": 10,
            "interfaces": [
                {
                    "index": 2,
                    "name": "enp1s0",
                    "status": 1,
                    "inOctets": 1000,
                    "outOctets": 2000,
                    "inErrors": 1,
                    "outErrors": 0,
                    "inDiscards": 0,
                    "outDiscards": 0,
                }
            ],
        }
        store_snmp_observations([observation], self.database_path)
        observation["uptimeTicks"] = 1100
        observation["interfaces"][0]["inOctets"] = 2000
        observation["interfaces"][0]["outOctets"] = 3000
        observation["interfaces"][0]["inErrors"] = 2
        store_snmp_observations([observation], self.database_path)

        dashboard = build_dashboard(self.database_path)
        saved = next(device for device in dashboard["snmpDevices"] if device["ip"] == observation["ip"])
        interface = saved["interfaces"][0]
        self.assertGreaterEqual(interface["trafficMbPerMinute"], 0)
        self.assertEqual(interface["errorsSinceLast"], 1)

    def test_counter_delta_handles_counter_wrap(self) -> None:
        self.assertEqual(counter_delta(3, 10, 16), 9)


if __name__ == "__main__":
    unittest.main()
