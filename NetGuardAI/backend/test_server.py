import json
import io
import os
import sqlite3
import socket
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from backend.server import (
    InventoryImportError,
    NetGuardHandler,
    OllamaRequestError,
    SecurityScanError,
    analyze_device_exposure_with_ollama,
    analyze_snmp_devices_with_ollama,
    analyze_dashboard_with_ollama,
    build_dashboard,
    check_ip_reachability,
    counter_delta,
    get_available_port,
    import_network_inventory,
    initialize_database,
    store_snmp_observations,
    scan_device_exposure,
    validate_snmp_devices_in_inventory,
    store_ping_observation,
)
from backend.ping_collector import (
    PingConfigurationError,
    PingMeasurement,
    PingTarget,
    load_ping_interval,
    load_ping_targets,
    parse_ping_output,
)
from backend.snmp_collector import (
    SnmpConfigurationError,
    SnmpDevice,
    load_credentials,
    load_devices,
)


class NetGuardBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.inventory_path = Path(self.temp_dir.name) / "laptop.csv"
        self.inventory_path.write_text(
            "ip,name,type\n"
            "192.168.1.48,Laptop,PC\n"
            "192.168.1.35,Celular,Movil\n",
            encoding="utf-8",
        )
        inventory_patcher = patch(
            "backend.server.LAPTOP_CSV_PATH", self.inventory_path
        )
        inventory_patcher.start()
        self.addCleanup(inventory_patcher.stop)
        initialize_database(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @contextmanager
    def _sqlite_connection(self, path: Path | None = None):
        connection = sqlite3.connect(path or self.database_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _insert_snmp_rate(
        self, ip: str, captured_at: datetime, rate: float
    ) -> None:
        with self._sqlite_connection() as connection:
            device = connection.execute(
                "SELECT id FROM devices WHERE ip = ?", (ip,)
            ).fetchone()
            connection.execute(
                """
                INSERT INTO snmp_observations (
                    device_id, captured_at, uptime_ticks, interfaces_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    device[0],
                    captured_at.isoformat(),
                    1000,
                    json.dumps(
                        [
                            {
                                "index": 2,
                                "name": "enp1s0",
                                "trafficMbPerMinute": rate,
                            }
                        ]
                    ),
                ),
            )

    def test_ollama_request_uses_local_chat_api_without_api_key(self) -> None:
        response = io.BytesIO(
            json.dumps(
                {"message": {"content": "Análisis de prueba."}}
            ).encode()
        )
        laptop_csv_path = Path(self.temp_dir.name) / "laptop.csv"
        laptop_csv_path.write_text(
            "ip,name,type\n192.168.1.48,Laptop,PC\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            with (
                patch("backend.server.OLLAMA_URL", "http://127.0.0.1:11434/api/chat"),
                patch("backend.server.OLLAMA_MODEL", "qwen2.5:3b"),
                patch("backend.server.LAPTOP_CSV_PATH", laptop_csv_path),
                patch("backend.server.urlopen", return_value=response) as mocked,
            ):
                analysis = analyze_dashboard_with_ollama(self.database_path)

        request = mocked.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(analysis, "Análisis de prueba.")
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(payload["model"], "qwen2.5:3b")
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertIn("192.168.1.48", payload["messages"][1]["content"])
        self.assertIn('"latencyMs": null', payload["messages"][1]["content"])
        self.assertIn("no asignes un nivel de riesgo", payload["messages"][0]["content"])
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"]["num_predict"], 700)

    def test_ollama_http_error_includes_provider_reason(self) -> None:
        provider_error = json.dumps(
            {"error": "model 'qwen2.5:3b' not found"}
        ).encode()
        http_error = HTTPError(
            "http://127.0.0.1:11434/api/chat",
            404,
            "Not Found",
            {},
            io.BytesIO(provider_error),
        )
        with patch("backend.server.urlopen", side_effect=http_error):
            with self.assertRaisesRegex(
                OllamaRequestError, "HTTP 404: model 'qwen2.5:3b' not found"
            ):
                analyze_dashboard_with_ollama(self.database_path)

    def test_device_exposure_analysis_uses_single_scan_and_limits_claims(self) -> None:
        scan = {
            "ip": "192.168.1.20",
            "checkedPorts": [
                {"port": 23, "service": "Telnet", "reachable": True}
            ],
            "exposedServices": [
                {
                    "port": 23,
                    "service": "Telnet",
                    "severity": "Alto",
                    "recommendation": "Deshabilita Telnet.",
                }
            ],
            "checkedAt": "2026-01-01T00:00:00+00:00",
            "note": "Comprobación de prueba.",
        }
        response = io.BytesIO(
            json.dumps(
                {"message": {"content": "Telnet está accesible; revisa su uso."}}
            ).encode()
        )
        with (
            patch("backend.server.scan_device_exposure", return_value=scan) as mocked_scan,
            patch("backend.server.urlopen", return_value=response) as mocked_ollama,
        ):
            result = analyze_device_exposure_with_ollama("192.168.1.20", True)

        payload = json.loads(mocked_ollama.call_args.args[0].data)
        self.assertEqual(result["scan"], scan)
        self.assertEqual(
            result["analysis"], "Telnet está accesible; revisa su uso."
        )
        mocked_scan.assert_called_once_with("192.168.1.20", True)
        self.assertIn("192.168.1.20", payload["messages"][1]["content"])
        self.assertIn("no contiene versiones", payload["messages"][0]["content"])
        self.assertIn("CVE", payload["messages"][0]["content"])
        self.assertEqual(payload["options"]["num_predict"], 500)

    def test_device_exposure_analysis_rejects_without_authorization(self) -> None:
        with (
            patch("backend.server.socket.socket") as socket_factory,
            patch("backend.server.urlopen") as mocked_ollama,
        ):
            with self.assertRaises(SecurityScanError):
                analyze_device_exposure_with_ollama("192.168.1.20", False)
        socket_factory.assert_not_called()
        mocked_ollama.assert_not_called()

    def test_snmp_device_analysis_checks_each_configured_private_device(self) -> None:
        devices = [
            SnmpDevice("Lab-A", "192.168.10.10", "Switch"),
            SnmpDevice("Lab-B", "192.168.10.11", "Router"),
        ]
        scan_results = [
            {
                "ip": device.ip,
                "checkedPorts": [],
                "exposedServices": [],
                "checkedAt": "2026-01-01T00:00:00+00:00",
                "note": "Comprobación de prueba.",
            }
            for device in devices
        ]
        dashboard = {
            "snmpDevices": [
                {"ip": "192.168.10.10", "uptimeSeconds": 120, "interfaces": []}
            ]
        }
        response = io.BytesIO(
            json.dumps(
                {"message": {"content": "Evaluación por dispositivo."}}
            ).encode()
        )
        with (
            patch("backend.server.load_devices", return_value=devices),
            patch(
                "backend.server.load_laptop_inventory",
                return_value=[
                    {"ip": "192.168.10.10"},
                    {"ip": "192.168.10.11"},
                ],
            ),
            patch("backend.server.build_dashboard", return_value=dashboard),
            patch(
                "backend.server.scan_device_exposure",
                side_effect=scan_results,
            ) as scan,
            patch("backend.server.urlopen", return_value=response) as mocked_ollama,
        ):
            result = analyze_snmp_devices_with_ollama(True)

        self.assertEqual(len(result["deviceResults"]), 2)
        self.assertEqual(
            [device["ip"] for device in result["deviceResults"]],
            ["192.168.10.10", "192.168.10.11"],
        )
        self.assertEqual(result["deviceResults"][0]["snmpObservation"], dashboard["snmpDevices"][0])
        self.assertIsNone(result["deviceResults"][1]["snmpObservation"])
        self.assertEqual(scan.call_count, 2)
        self.assertTrue(all(call.args[1] is True for call in scan.call_args_list))
        prompt = json.loads(mocked_ollama.call_args.args[0].data)["messages"]
        self.assertIn("192.168.10.10", prompt[1]["content"])
        self.assertIn("datos CVE", prompt[0]["content"])

    def test_snmp_device_analysis_requires_explicit_authorization(self) -> None:
        with patch("backend.server.load_devices") as load_config:
            with self.assertRaises(SecurityScanError):
                analyze_snmp_devices_with_ollama(False)
        load_config.assert_not_called()

    def test_dashboard_uses_only_laptop_csv_and_does_not_invent_telemetry(self) -> None:
        dashboard = build_dashboard(self.database_path)

        self.assertEqual(dashboard["mode"], "inventario_csv")
        self.assertEqual(dashboard["summary"]["monitoredDevices"], 2)
        self.assertEqual(
            {device["ip"] for device in dashboard["devices"]},
            {"192.168.1.48", "192.168.1.35"},
        )
        self.assertTrue(
            all(device["status"] == "Sin métricas" for device in dashboard["devices"])
        )
        self.assertTrue(all(device["latencyMs"] is None for device in dashboard["devices"]))
        self.assertIsNone(dashboard["riskIndex"])
        self.assertEqual(dashboard["riskLevel"], "Sin datos")
        self.assertEqual(dashboard["alerts"], [])
        self.assertEqual(dashboard["traffic"], [])

    def test_dashboard_preserves_legacy_synthetic_rows_and_obsolete_devices(self) -> None:
        with self._sqlite_connection() as connection:
            obsolete = connection.execute(
                "INSERT INTO devices (name, ip, type) VALUES (?, ?, ?)",
                ("PC-A", "192.168.1.15", "Computadora"),
            ).lastrowid
            peer = connection.execute(
                "INSERT INTO devices (name, ip, type) VALUES (?, ?, ?)",
                ("SW-01", "192.168.1.2", "Switch"),
            ).lastrowid
            other_real_device = connection.execute(
                "INSERT INTO devices (name, ip, type) VALUES (?, ?, ?)",
                ("Camera", "192.168.1.99", "Camera"),
            ).lastrowid
            event_id = connection.execute(
                """
                INSERT INTO events (
                    device_id, captured_at, metric, activity, magnitude,
                    confidence, risk_score, risk_level, recommendation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obsolete,
                    "2026-01-01T00:00:00+00:00",
                    "traffic_mb",
                    "Evento ficticio",
                    "42 MB/min",
                    0.9,
                    80,
                    "Alto",
                    "Revisar",
                ),
            ).lastrowid
            connection.execute(
                """
                INSERT INTO metrics (
                    device_id, captured_at, latency_ms, packet_loss_pct, errors,
                    availability_pct, traffic_mb, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (obsolete, "2026-01-01T00:00:00+00:00", 18, 0, 0, 100, 12, "simulado"),
            )
            connection.execute(
                "INSERT INTO topology (source_id, target_id) VALUES (?, ?)",
                (obsolete, peer),
            )
            connection.execute(
                """
                INSERT INTO metrics (
                    device_id, captured_at, latency_ms, packet_loss_pct, errors,
                    availability_pct, traffic_mb, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    other_real_device,
                    "2026-01-01T00:00:00+00:00",
                    5,
                    0,
                    0,
                    100,
                    8,
                    "SNMPv3",
                ),
            )
            connection.execute(
                """
                INSERT INTO predictions (
                    event_id, device_id, hop_count, confidence, reason
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, peer, 1, 0.4, "Predicción sintética"),
            )

        dashboard = build_dashboard(self.database_path)

        self.assertEqual(dashboard["summary"]["monitoredDevices"], 2)
        self.assertEqual(dashboard["summary"]["anomalies"], 0)
        with self._sqlite_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0], 5
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM metrics WHERE source = 'simulado'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM metrics WHERE source = 'SNMPv3'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM topology").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 1
            )

    def test_dhcp_inventory_import_replaces_snapshot_without_snmp(self) -> None:
        csv_content = (
            "IP Address;Hostname;MAC Address;Type\n"
            "192.168.1.48;Phone;aa-bb-cc-dd-ee-20;Mobile\n"
            "192.168.1.35;Laptop;aa-bb-cc-dd-ee-21;Computer\n"
        )
        self.assertEqual(
            import_network_inventory(csv_content, self.database_path), 2
        )
        dashboard = build_dashboard(self.database_path)
        self.assertEqual(
            [device["name"] for device in dashboard["networkInventory"]],
            ["Laptop", "Phone"],
        )
        self.assertEqual(
            dashboard["networkInventory"][1]["mac"], "aa:bb:cc:dd:ee:20"
        )

        self.assertEqual(
            import_network_inventory("ip,name\n192.168.1.35,Tablet\n", self.database_path),
            1,
        )
        replaced = build_dashboard(self.database_path)["networkInventory"]
        self.assertEqual([device["ip"] for device in replaced], ["192.168.1.35"])

    def test_dhcp_inventory_import_rejects_unsafe_or_ambiguous_rows(self) -> None:
        invalid_csvs = [
            "ip,name\n8.8.8.8,Public\n",
            "ip,name\n192.168.1.20,First\n192.168.1.20,Duplicate\n",
            "ip,name,mac\n192.168.1.20,Invalid,not-a-mac\n",
            "ip,name\n192.168.1.20,Duplicate\n192.168.1.21,Duplicate\n",
            "name\nNo IP column\n",
        ]
        for csv_content in invalid_csvs:
            with self.subTest(csv_content=csv_content):
                with self.assertRaises(InventoryImportError):
                    import_network_inventory(csv_content, self.database_path)

    def test_inventory_import_api_does_not_require_snmp_configuration(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), NetGuardHandler)
        thread = threading.Thread(target=server.serve_forever)
        csv_content = "ip,name\n192.168.1.48,Phone\n"
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/inventory/import",
            data=csv_content.encode("utf-8"),
            headers={"Content-Type": "text/csv"},
            method="POST",
        )
        try:
            with (
                patch("backend.server.DATABASE_PATH", self.database_path),
                patch("backend.server.DATABASE_URL", None),
                patch.dict(os.environ, {}, clear=True),
            ):
                thread.start()
                with urlopen(request) as response:
                    result = json.load(response)
                self.assertEqual(result["imported"], 1)
                with urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/dashboard"
                ) as response:
                    dashboard = json.load(response)
                self.assertEqual(
                    dashboard["networkInventory"][0]["ip"], "192.168.1.48"
                )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_security_scan_api_requires_authorization(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), NetGuardHandler)
        thread = threading.Thread(target=server.serve_forever)
        result_payload = {
            "ip": "192.168.1.20",
            "checkedPorts": [],
            "exposedServices": [],
            "checkedAt": "2026-01-01T00:00:00+00:00",
            "note": "Comprobación de prueba.",
        }
        try:
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/api/security/scan"
            unauthorized_request = Request(
                url,
                data=json.dumps(
                    {"ip": "192.168.1.20", "authorized": False}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(unauthorized_request)
            self.assertEqual(error.exception.code, 400)

            authorized_request = Request(
                url,
                data=json.dumps(
                    {"ip": "192.168.1.20", "authorized": True}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with patch(
                "backend.server.scan_device_exposure",
                return_value=result_payload,
            ) as scan:
                with urlopen(authorized_request) as response:
                    result = json.load(response)
            scan.assert_called_once_with("192.168.1.20", True)
            self.assertEqual(result, result_payload)

            analyze_request = Request(
                f"http://127.0.0.1:{server.server_port}/api/security/analyze",
                data=json.dumps(
                    {"ip": "192.168.1.20", "authorized": True}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            analysis_payload = {
                "scan": result_payload,
                "analysis": "Evaluación preliminar.",
            }
            with patch(
                "backend.server.analyze_device_exposure_with_ollama",
                return_value=analysis_payload,
            ) as analyze:
                with urlopen(analyze_request) as response:
                    analysis = json.load(response)
            analyze.assert_called_once_with("192.168.1.20", True)
            self.assertEqual(analysis["analysis"], "Evaluación preliminar.")
            self.assertEqual(analysis["provider"], "Ollama")

            snmp_url = (
                f"http://127.0.0.1:{server.server_port}/api/security/analyze-snmp"
            )
            unauthorized_snmp_request = Request(
                snmp_url,
                data=json.dumps({"authorized": False}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(unauthorized_snmp_request)
            self.assertEqual(error.exception.code, 400)

            authorized_snmp_request = Request(
                snmp_url,
                data=json.dumps({"authorized": True}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            snmp_result = {
                "deviceResults": [],
                "analysis": "Riesgos revisados.",
            }
            with patch(
                "backend.server.analyze_snmp_devices_with_ollama",
                return_value=snmp_result,
            ) as analyze_snmp:
                with urlopen(authorized_snmp_request) as response:
                    snmp_analysis = json.load(response)
            analyze_snmp.assert_called_once_with(True)
            self.assertEqual(snmp_analysis["analysis"], "Riesgos revisados.")
            self.assertEqual(snmp_analysis["provider"], "Ollama")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_initialization_preserves_legacy_devices_and_syncs_csv(self) -> None:
        partial_database = Path(self.temp_dir.name) / "partial.sqlite3"
        with self._sqlite_connection(partial_database) as connection:
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

        self.inventory_path.write_text(
            "ip,name,type\n"
            "192.168.1.48,PC-A,Computadora\n"
            "192.168.1.35,Celular,Movil\n",
            encoding="utf-8",
        )
        initialize_database(partial_database)
        dashboard = build_dashboard(partial_database)
        self.assertEqual(dashboard["summary"]["monitoredDevices"], 2)
        self.assertEqual(
            {device["ip"] for device in dashboard["devices"]},
            {"192.168.1.48", "192.168.1.35"},
        )
        self.assertEqual(dashboard["alerts"], [])
        with self._sqlite_connection(partial_database) as connection:
            migrated = connection.execute(
                "SELECT name, ip FROM devices WHERE name = ?",
                ("PC-A",),
            ).fetchone()
        self.assertEqual(migrated, ("PC-A", "192.168.1.48"))

    def test_available_port_skips_busy_ports(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        busy_port = listener.getsockname()[1]

        self.addCleanup(listener.close)
        self.assertIsInstance(get_available_port(busy_port), int)
        self.assertNotEqual(get_available_port(busy_port), busy_port)

    def test_ping_configuration_is_private_and_matches_inventory(self) -> None:
        targets = load_ping_targets(
            {"192.168.1.48"},
            '[{"device_ip":"192.168.1.48","target_ip":"192.168.1.1"}]',
        )
        self.assertEqual(
            targets,
            [PingTarget("192.168.1.48", "192.168.1.1")],
        )
        self.assertEqual(load_ping_interval("60"), 60)

        with self.assertRaises(PingConfigurationError):
            load_ping_targets(
                {"192.168.1.48"},
                '[{"device_ip":"192.168.1.35","target_ip":"192.168.1.1"}]',
            )
        with self.assertRaises(PingConfigurationError):
            load_ping_targets(
                {"192.168.1.48"},
                '[{"device_ip":"192.168.1.48","target_ip":"8.8.8.8"}]',
            )

    def test_ping_output_calculates_loss_and_average_latency(self) -> None:
        measurement = parse_ping_output(
            "5 packets transmitted, 4 received, 20% packet loss, time 4000ms\n"
            "rtt min/avg/max/mdev = 0.050/0.075/0.100/0.020 ms\n"
        )
        self.assertEqual(
            measurement,
            PingMeasurement(5, 4, 0.075, 20.0),
        )

        no_reply = parse_ping_output(
            "5 packets transmitted, 0 received, 100% packet loss, time 4000ms\n"
        )
        self.assertEqual(no_reply.latency_ms, None)
        self.assertEqual(no_reply.packet_loss_pct, 100.0)

    def test_ping_observation_appears_in_device_metrics(self) -> None:
        store_ping_observation(
            PingTarget("192.168.1.48", "192.168.1.1"),
            PingMeasurement(5, 4, 0.075, 20.0),
            self.database_path,
        )

        dashboard = build_dashboard(self.database_path)
        device = next(
            item for item in dashboard["devices"] if item["ip"] == "192.168.1.48"
        )
        self.assertEqual(device["source"], "ICMP")
        self.assertEqual(device["pingTarget"], "192.168.1.1")
        self.assertEqual(device["latencyMs"], 0.075)
        self.assertEqual(device["packetLossPct"], 20.0)
        self.assertEqual(device["availabilityPct"], 80.0)
        self.assertIsNone(device["trafficMb"])

    def test_snmp_configuration_accepts_one_or_more_private_lab_hosts(self) -> None:
        single_device = load_devices('[{"name":"Lenovo","ip":"192.168.1.48"}]')
        self.assertEqual(len(single_device), 1)

        multiple_devices = load_devices(
            '[{"name":"Lenovo","ip":"192.168.1.48"},'
            '{"name":"Toshiba","ip":"192.168.1.45"}]'
        )
        self.assertEqual(len(multiple_devices), 2)

        with self.assertRaisesRegex(SnmpConfigurationError, "al menos un equipo"):
            load_devices("[]")

        with self.assertRaises(SnmpConfigurationError):
            load_devices('[{"name":"public","ip":"8.8.8.8"}]')

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

    def test_snmp_devices_must_be_listed_in_laptop_csv(self) -> None:
        devices = [
            SnmpDevice("Laptop", "192.168.1.48", "PC"),
            SnmpDevice("Other", "192.168.1.45", "PC"),
        ]
        with patch(
            "backend.server.load_laptop_inventory",
            return_value=[{"ip": "192.168.1.48"}],
        ):
            with self.assertRaisesRegex(SnmpConfigurationError, "laptop.csv"):
                validate_snmp_devices_in_inventory(devices)

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
        observation["interfaces"][0]["outErrors"] = 1
        observation["interfaces"][0]["inDiscards"] = 1
        observation["interfaces"][0]["outDiscards"] = 2
        store_snmp_observations([observation], self.database_path)

        dashboard = build_dashboard(self.database_path)
        saved = next(device for device in dashboard["snmpDevices"] if device["ip"] == observation["ip"])
        interface = saved["interfaces"][0]
        self.assertGreaterEqual(interface["trafficMbPerMinute"], 0)
        self.assertIsNotNone(interface["inTrafficMbPerMinute"])
        self.assertIsNotNone(interface["outTrafficMbPerMinute"])
        self.assertAlmostEqual(
            interface["trafficMbPerMinute"],
            interface["inTrafficMbPerMinute"]
            + interface["outTrafficMbPerMinute"],
            delta=0.02,
        )
        self.assertEqual(interface["errorsSinceLast"], 2)
        self.assertEqual(interface["inErrorsSinceLast"], 1)
        self.assertEqual(interface["outErrorsSinceLast"], 1)
        self.assertEqual(interface["inDiscardsSinceLast"], 1)
        self.assertEqual(interface["outDiscardsSinceLast"], 2)

    def test_risk_index_uses_max_confirmed_snmp_anomaly_across_devices(self) -> None:
        now = datetime.now(timezone.utc)
        baseline_at = now - timedelta(minutes=20)
        self._insert_snmp_rate("192.168.1.48", baseline_at, 100)
        self._insert_snmp_rate("192.168.1.48", now - timedelta(minutes=10), 150)
        self._insert_snmp_rate("192.168.1.48", now - timedelta(minutes=5), 150)
        self._insert_snmp_rate("192.168.1.35", baseline_at, 100)
        self._insert_snmp_rate("192.168.1.35", now - timedelta(minutes=10), 300)
        self._insert_snmp_rate("192.168.1.35", now - timedelta(minutes=5), 300)

        dashboard = build_dashboard(self.database_path)

        self.assertEqual(dashboard["riskIndex"], 100)
        self.assertEqual(dashboard["riskLevel"], "Elevado")
        self.assertEqual(
            dashboard["riskCoverage"],
            {
                "devicesWithRecentSnmp": 2,
                "devicesInInventory": 2,
                "interfacesEvaluated": 2,
            },
        )
        findings_by_ip = {
            finding["ip"]: finding for finding in dashboard["riskFindings"]
        }
        self.assertEqual(findings_by_ip["192.168.1.48"]["riskScore"], 25)
        self.assertEqual(findings_by_ip["192.168.1.35"]["riskScore"], 100)

    def test_risk_index_ignores_large_percentage_change_on_low_traffic(self) -> None:
        now = datetime.now(timezone.utc)
        self._insert_snmp_rate("192.168.1.48", now - timedelta(minutes=15), 0.08)
        self._insert_snmp_rate("192.168.1.48", now - timedelta(minutes=10), 1.51)
        self._insert_snmp_rate("192.168.1.48", now - timedelta(minutes=5), 0.37)

        dashboard = build_dashboard(self.database_path)

        self.assertIsNone(dashboard["riskIndex"])
        self.assertEqual(dashboard["riskFindings"], [])

    def test_risk_index_requires_baseline_and_two_consecutive_recent_polls(self) -> None:
        now = datetime.now(timezone.utc)
        self._insert_snmp_rate("192.168.1.48", now - timedelta(minutes=15), 100)
        self._insert_snmp_rate("192.168.1.48", now - timedelta(minutes=10), 200)

        dashboard = build_dashboard(self.database_path)

        self.assertIsNone(dashboard["riskIndex"])
        self.assertEqual(dashboard["riskCoverage"]["interfacesEvaluated"], 0)

        self._insert_snmp_rate("192.168.1.48", now - timedelta(minutes=5), 200)
        dashboard = build_dashboard(self.database_path)

        self.assertEqual(dashboard["riskIndex"], 50)
        self.assertEqual(dashboard["riskLevel"], "Moderado")
        self.assertEqual(
            dashboard["riskFindings"][0]["increasePct"],
            100.0,
        )

    def test_risk_index_ignores_snmp_observations_older_than_24_hours(self) -> None:
        self._insert_snmp_rate(
            "192.168.1.48",
            datetime.now(timezone.utc) - timedelta(hours=25),
            100,
        )

        dashboard = build_dashboard(self.database_path)

        self.assertIsNone(dashboard["riskIndex"])
        self.assertEqual(dashboard["riskCoverage"]["devicesWithRecentSnmp"], 0)
        self.assertEqual(dashboard["riskFindings"], [])

    def test_counter_delta_handles_counter_wrap(self) -> None:
        self.assertEqual(counter_delta(3, 10, 16), 9)

    def test_ip_reachability_requires_authorization_and_checks_one_private_ip(self) -> None:
        with patch("backend.server.subprocess.run") as run:
            run.return_value.returncode = 0
            result = check_ip_reachability("192.168.1.20", True)

            run.assert_called_once()
            self.assertEqual(
                run.call_args.args[0],
                ["ping", "-c", "1", "-W", "1", "192.168.1.20"],
            )
            self.assertEqual(run.call_args.kwargs["timeout"], 2)
            self.assertTrue(result["reachable"])
            self.assertEqual(result["ip"], "192.168.1.20")

            for ip, authorized in (
                ("192.168.1.20", False),
                ("8.8.8.8", True),
                ("2001:db8::1", True),
            ):
                with self.assertRaises(SecurityScanError):
                    check_ip_reachability(ip, authorized)
            run.assert_called_once()

    def test_ip_reachability_reports_no_icmp_response_as_inconclusive(self) -> None:
        with patch("backend.server.subprocess.run") as run:
            run.return_value.returncode = 1
            result = check_ip_reachability("192.168.1.20", True)

        self.assertFalse(result["reachable"])
        self.assertIn("no confirma que la IP no exista", result["note"])

    def test_ip_reachability_api_requires_authorization(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), NetGuardHandler)
        thread = threading.Thread(target=server.serve_forever)
        try:
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/api/network/check-ip"
            request = Request(
                url,
                data=json.dumps(
                    {"ip": "192.168.1.20", "authorized": False}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 400)

            request = Request(
                url,
                data=json.dumps(
                    {"ip": "192.168.1.20", "authorized": True}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            expected = {
                "ip": "192.168.1.20",
                "reachable": True,
                "checkedAt": "2026-01-01T00:00:00+00:00",
                "note": "La IP respondió a una solicitud ICMP.",
            }
            with patch(
                "backend.server.check_ip_reachability", return_value=expected
            ) as check:
                with urlopen(request) as response:
                    self.assertEqual(json.load(response), expected)
            check.assert_called_once_with("192.168.1.20", True)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_security_scan_only_checks_fixed_ports_on_authorized_private_ip(self) -> None:
        with patch("backend.server.socket.socket") as socket_factory:
            connection = socket_factory.return_value.__enter__.return_value
            connection.connect_ex.side_effect = [1, 0, 1, 1, 1, 1, 1]

            result = scan_device_exposure("192.168.1.20", True)

        self.assertEqual(len(result["checkedPorts"]), 7)
        self.assertEqual(
            result["exposedServices"],
            [
                {
                    "port": 22,
                    "service": "SSH",
                    "severity": "Bajo",
                    "recommendation": (
                        "Restringe el acceso y usa claves seguras y actualizadas."
                    ),
                }
            ],
        )
        self.assertEqual(connection.connect_ex.call_count, 7)
        self.assertEqual(
            connection.connect_ex.call_args_list[0].args[0], ("192.168.1.20", 21)
        )
        self.assertEqual(
            connection.connect_ex.call_args_list[-1].args[0], ("192.168.1.20", 5900)
        )

    def test_security_scan_rejects_missing_authorization_and_public_ip(self) -> None:
        with patch("backend.server.socket.socket") as socket_factory:
            with self.assertRaises(SecurityScanError):
                scan_device_exposure("192.168.1.20", False)
            with self.assertRaises(SecurityScanError):
                scan_device_exposure("8.8.8.8", True)

        socket_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
