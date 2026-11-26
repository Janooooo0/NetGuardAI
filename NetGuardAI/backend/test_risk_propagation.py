import gc
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.risk_propagation import (
    CONFIDENCE_DECAY,
    MAX_HOPS,
    MIN_CONFIDENCE,
    build_adjacency,
    predict_affected,
)
from backend.ping_collector import PingMeasurement, PingTarget
from backend.server import initialize_database, store_ping_observation


class RiskPropagationUnitTests(unittest.TestCase):
    def test_build_adjacency_is_undirected(self) -> None:
        adjacency = build_adjacency([(1, 2), (2, 3)])

        self.assertEqual(adjacency[1], {2})
        self.assertEqual(adjacency[2], {1, 3})
        self.assertEqual(adjacency[3], {2})
        # Cada arista se registra en ambos sentidos.
        self.assertIn(2, adjacency[1])
        self.assertIn(1, adjacency[2])

    def test_predict_affected_returns_bfs_hops_in_order(self) -> None:
        adjacency = build_adjacency([(1, 2), (1, 3), (2, 4), (3, 5)])

        affected = predict_affected(adjacency, 1, 1.0)

        self.assertEqual(
            [(device_id, hops) for device_id, hops, _ in affected],
            [(2, 1), (3, 1), (4, 2), (5, 2)],
        )

    def test_predict_affected_confidence_decays_by_seven_tenths_per_hop(self) -> None:
        self.assertEqual(CONFIDENCE_DECAY, 0.7)
        adjacency = build_adjacency([(1, 2), (2, 3), (3, 4)])

        affected = predict_affected(adjacency, 1, 0.9)

        self.assertEqual([hops for _, hops, _ in affected], [1, 2, 3])
        for _, hops, confidence in affected:
            self.assertAlmostEqual(
                confidence, round(0.9 * 0.7 ** hops, 3), places=6
            )

    def test_predict_affected_respects_default_max_hops_of_three(self) -> None:
        self.assertEqual(MAX_HOPS, 3)
        adjacency = build_adjacency([(1, 2), (2, 3), (3, 4), (4, 5)])

        affected = predict_affected(adjacency, 1, 1.0)

        self.assertEqual(
            [(device_id, hops) for device_id, hops, _ in affected],
            [(2, 1), (3, 2), (4, 3)],
        )
        self.assertNotIn(5, [device_id for device_id, _, _ in affected])

    def test_predict_affected_respects_explicit_max_hops(self) -> None:
        adjacency = build_adjacency([(1, 2), (2, 3), (3, 4)])

        affected = predict_affected(adjacency, 1, 1.0, max_hops=1)

        self.assertEqual(
            [(device_id, hops) for device_id, hops, _ in affected],
            [(2, 1)],
        )

    def test_predict_affected_respects_min_confidence(self) -> None:
        self.assertEqual(MIN_CONFIDENCE, 0.15)
        adjacency = build_adjacency([(1, 2), (2, 3), (3, 4)])

        affected = predict_affected(adjacency, 1, 0.5, min_confidence=0.2)

        # 0.5*0.7 = 0.35 y 0.5*0.7^2 = 0.245 se conservan;
        # 0.5*0.7^3 = 0.1715 < 0.2 se descarta.
        self.assertEqual(
            [(device_id, hops) for device_id, hops, _ in affected],
            [(2, 1), (3, 2)],
        )

    def test_predict_affected_excludes_origin(self) -> None:
        adjacency = build_adjacency([(1, 2), (2, 3), (3, 1)])

        affected = predict_affected(adjacency, 1, 0.9)

        self.assertNotIn(1, [device_id for device_id, _, _ in affected])

    def test_predict_affected_handles_cycles_without_duplicates(self) -> None:
        adjacency = build_adjacency([(1, 2), (2, 3), (3, 1)])

        affected = predict_affected(adjacency, 1, 0.9)

        self.assertEqual(
            [(device_id, hops) for device_id, hops, _ in affected],
            [(2, 1), (3, 1)],
        )
        device_ids = [device_id for device_id, _, _ in affected]
        self.assertEqual(len(device_ids), len(set(device_ids)))

    def test_predict_affected_returns_empty_for_isolated_origin(self) -> None:
        self.assertEqual(predict_affected({7: set()}, 7, 0.9), [])


class RiskPropagationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.inventory_path = Path(self.temp_dir.name) / "laptop.csv"
        self.inventory_path.write_text(
            "ip,name,type,uplink\n"
            "192.168.1.1,Router,Router,\n"
            "192.168.1.2,Switch,Switch,192.168.1.1\n"
            "192.168.1.10,PC-A,PC,192.168.1.2\n"
            "192.168.1.11,PC-B,PC,192.168.1.2\n",
            encoding="utf-8",
        )
        inventory_patcher = patch(
            "backend.server.LAPTOP_CSV_PATH", self.inventory_path
        )
        inventory_patcher.start()
        self.addCleanup(inventory_patcher.stop)
        initialize_database(self.database_path)

    def tearDown(self) -> None:
        gc.collect()
        self.temp_dir.cleanup()

    @contextmanager
    def _sqlite_connection(self, path: Path | None = None):
        connection = sqlite3.connect(path or self.database_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def test_ping_loss_records_event_and_propagates_predictions(self) -> None:
        with self._sqlite_connection() as connection:
            topology_count = connection.execute(
                "SELECT COUNT(*) FROM topology"
            ).fetchone()[0]
        self.assertEqual(topology_count, 3)

        target = PingTarget("192.168.1.10", "192.168.1.1")
        measurement = PingMeasurement(5, 0, None, 100.0)
        store_ping_observation(target, measurement, self.database_path)

        with self._sqlite_connection() as connection:
            event_rows = connection.execute("SELECT id, device_id FROM events").fetchall()
            self.assertEqual(len(event_rows), 1)
            event_id, origin_id = event_rows[0]

            origin_ip = connection.execute(
                "SELECT ip FROM devices WHERE id = ?", (origin_id,)
            ).fetchone()[0]
            self.assertEqual(origin_ip, "192.168.1.10")

            prediction_rows = connection.execute(
                """
                SELECT devices.ip, predictions.hop_count
                FROM predictions
                JOIN devices ON devices.id = predictions.device_id
                WHERE predictions.event_id = ?
                """,
                (event_id,),
            ).fetchall()

        hops_by_ip = {ip: hops for ip, hops in prediction_rows}
        self.assertEqual(
            hops_by_ip,
            {
                "192.168.1.2": 1,
                "192.168.1.1": 2,
                "192.168.1.11": 2,
            },
        )

    def test_repeated_ping_loss_within_window_does_not_duplicate_event(self) -> None:
        target = PingTarget("192.168.1.10", "192.168.1.1")
        measurement = PingMeasurement(5, 0, None, 100.0)

        store_ping_observation(target, measurement, self.database_path)
        store_ping_observation(target, measurement, self.database_path)

        with self._sqlite_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0],
                3,
            )


if __name__ == "__main__":
    unittest.main()
