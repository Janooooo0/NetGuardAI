import tempfile
import unittest
from pathlib import Path

from backend.server import build_dashboard, initialize_database, simulate_observation


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


if __name__ == "__main__":
    unittest.main()
