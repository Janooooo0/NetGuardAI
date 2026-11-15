import json
import logging
import random
import sqlite3
import statistics
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit


DATABASE_PATH = Path(__file__).with_name("netguard.sqlite3")
HOST = "127.0.0.1"
PORT = 8000

DEVICES = [
    ("PC-A", "192.168.1.15", "Computadora"),
    ("SW-01", "192.168.1.2", "Switch"),
    ("RTR-01", "192.168.1.1", "Router"),
    ("SERVER-01", "192.168.1.10", "Servidor"),
    ("PC-B", "192.168.1.16", "Computadora"),
]

TOPOLOGY = [
    ("PC-A", "SW-01"),
    ("PC-B", "SW-01"),
    ("SERVER-01", "SW-01"),
    ("SW-01", "RTR-01"),
]

METRIC_COLUMNS = (
    "latency_ms",
    "packet_loss_pct",
    "errors",
    "availability_pct",
    "traffic_mb",
)

METRIC_LABELS = {
    "latency_ms": ("Latencia", "ms"),
    "packet_loss_pct": ("Pérdida de paquetes", "%"),
    "errors": ("Errores", "errores"),
    "traffic_mb": ("Tráfico", "MB/min"),
}

SCENARIOS = {
    "latency_ms": {
        "activity": "Aumento inusual de latencia",
        "minimum_delta": 15.0,
        "impact": 10,
        "recommendation": "Revisar latencia, rutas y carga del dispositivo.",
    },
    "packet_loss_pct": {
        "activity": "Pérdida inusual de paquetes",
        "minimum_delta": 1.5,
        "impact": 15,
        "recommendation": "Verificar pérdida de paquetes, enlaces y contadores de interfaz.",
    },
    "errors": {
        "activity": "Incremento inusual de errores",
        "minimum_delta": 3.0,
        "impact": 15,
        "recommendation": "Revisar contadores de errores, puertos y registros del dispositivo.",
    },
    "traffic_mb": {
        "activity": "Aumento inusual de tráfico",
        "minimum_delta": 5.0,
        "impact": 10,
        "recommendation": "Comparar el tráfico con la línea base y revisar las conexiones observadas.",
    },
}

SEED_METRICS = {
    "PC-A": [
        (18, 0.1, 0, 99.9, 12),
        (19, 0.1, 0, 99.9, 14),
        (17, 0.1, 1, 99.9, 13),
        (18, 0.2, 0, 99.9, 15),
        (19, 0.1, 0, 99.8, 14),
        (18, 0.1, 0, 99.9, 13),
    ],
    "SW-01": [
        (4, 0.1, 0, 99.9, 3),
        (5, 0.1, 1, 99.9, 3),
        (4, 0.1, 1, 99.9, 4),
        (7, 0.2, 2, 99.8, 4),
        (12, 0.3, 5, 99.6, 5),
        (25, 0.3, 14, 99.1, 6),
    ],
    "RTR-01": [
        (3, 0, 0, 100, 8),
        (3, 0, 0, 100, 9),
        (4, 0, 0, 100, 8),
        (3, 0, 0, 100, 8),
        (3, 0, 0, 100, 9),
        (4, 0, 0, 100, 8),
    ],
    "SERVER-01": [
        (8, 0.1, 0, 99.9, 22),
        (8, 0.1, 0, 99.9, 23),
        (9, 0.1, 1, 99.8, 22),
        (10, 0.1, 0, 99.8, 24),
        (14, 0.2, 1, 99.6, 25),
        (24, 0.2, 1, 99.2, 24),
    ],
    "PC-B": [
        (16, 0.1, 0, 99.9, 10),
        (17, 0.1, 0, 99.9, 11),
        (16, 0.1, 0, 99.9, 10),
        (16, 0.1, 1, 99.9, 12),
        (17, 0.1, 0, 99.9, 11),
        (16, 0.1, 0, 99.9, 10),
    ],
}

SEED_EVENTS = [
    {
        "device": "PC-A",
        "minutes_ago": 18,
        "metric": "traffic_mb",
        "activity": "Aumento inusual de tráfico",
        "magnitude": "42 MB/min (+180% sobre la línea base)",
        "confidence": 0.91,
        "risk_score": 82,
        "recommendation": "Comparar el tráfico con la línea base y revisar las conexiones observadas.",
    },
    {
        "device": "SW-01",
        "minutes_ago": 12,
        "metric": "errors",
        "activity": "Incremento de errores",
        "magnitude": "14 errores (+10 respecto a la línea base)",
        "confidence": 0.78,
        "risk_score": 59,
        "recommendation": "Revisar contadores de errores, puertos y registros del dispositivo.",
    },
    {
        "device": "SERVER-01",
        "minutes_ago": 5,
        "metric": "latency_ms",
        "activity": "Latencia elevada",
        "magnitude": "24 ms (+16 ms respecto a la línea base)",
        "confidence": 0.74,
        "risk_score": 63,
        "recommendation": "Revisar latencia, rutas y carga del dispositivo.",
    },
]


@contextmanager
def database(path: Path = DATABASE_PATH) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def timestamp(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def initialize_database(path: Path = DATABASE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with database(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                ip TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS topology (
                source_id INTEGER NOT NULL REFERENCES devices(id),
                target_id INTEGER NOT NULL REFERENCES devices(id),
                PRIMARY KEY (source_id, target_id),
                CHECK (source_id != target_id)
            );
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY,
                device_id INTEGER NOT NULL REFERENCES devices(id),
                captured_at TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                packet_loss_pct REAL NOT NULL,
                errors REAL NOT NULL,
                availability_pct REAL NOT NULL,
                traffic_mb REAL NOT NULL,
                source TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS metrics_device_time
                ON metrics(device_id, captured_at);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                device_id INTEGER NOT NULL REFERENCES devices(id),
                captured_at TEXT NOT NULL,
                metric TEXT NOT NULL,
                activity TEXT NOT NULL,
                magnitude TEXT NOT NULL,
                confidence REAL NOT NULL,
                risk_score INTEGER NOT NULL,
                risk_level TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Sin revisar'
            );
            CREATE INDEX IF NOT EXISTS events_time ON events(captured_at);
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY,
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                device_id INTEGER NOT NULL REFERENCES devices(id),
                hop_count INTEGER NOT NULL,
                confidence REAL NOT NULL,
                reason TEXT NOT NULL,
                UNIQUE(event_id, device_id)
            );
            """
        )
        device_count = connection.execute(
            "SELECT COUNT(*) FROM devices"
        ).fetchone()[0]
        if device_count == 0:
            seed_database(connection)


def seed_database(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT INTO devices (name, ip, type) VALUES (?, ?, ?)", DEVICES
    )
    device_ids = {
        row["name"]: row["id"]
        for row in connection.execute("SELECT id, name FROM devices")
    }

    connection.executemany(
        "INSERT INTO topology (source_id, target_id) VALUES (?, ?)",
        [(device_ids[left], device_ids[right]) for left, right in TOPOLOGY],
    )

    now = datetime.now(timezone.utc)
    metric_rows = []
    for device_name, measurements in SEED_METRICS.items():
        device_id = device_ids[device_name]
        for index, values in enumerate(measurements):
            measured_at = now - timedelta(minutes=(len(measurements) - index) * 30)
            metric_rows.append(
                (device_id, timestamp(measured_at), *values, "simulado")
            )
    connection.executemany(
        """
        INSERT INTO metrics (
            device_id, captured_at, latency_ms, packet_loss_pct, errors,
            availability_pct, traffic_mb, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        metric_rows,
    )

    for event in SEED_EVENTS:
        event_id = insert_event(
            connection,
            device_id=device_ids[event["device"]],
            captured_at=timestamp(now - timedelta(minutes=event["minutes_ago"])),
            metric=event["metric"],
            activity=event["activity"],
            magnitude=event["magnitude"],
            confidence=event["confidence"],
            risk_score=event["risk_score"],
            recommendation=event["recommendation"],
        )
        create_predictions(connection, event_id, device_ids[event["device"]])


def risk_level(score: int) -> str:
    if score >= 75:
        return "Alto"
    if score >= 50:
        return "Medio"
    return "Bajo"


def risk_css_class(level: str) -> str:
    return {"Alto": "high", "Medio": "medium", "Bajo": "normal"}[level]


def insert_event(
    connection: sqlite3.Connection,
    *,
    device_id: int,
    captured_at: str,
    metric: str,
    activity: str,
    magnitude: str,
    confidence: float,
    risk_score: int,
    recommendation: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO events (
            device_id, captured_at, metric, activity, magnitude, confidence,
            risk_score, risk_level, recommendation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            device_id,
            captured_at,
            metric,
            activity,
            magnitude,
            confidence,
            risk_score,
            risk_level(risk_score),
            recommendation,
        ),
    )
    return cursor.lastrowid


def create_predictions(
    connection: sqlite3.Connection, event_id: int, origin_id: int
) -> None:
    neighbors: dict[int, set[int]] = {}
    for edge in connection.execute("SELECT source_id, target_id FROM topology"):
        neighbors.setdefault(edge["source_id"], set()).add(edge["target_id"])
        neighbors.setdefault(edge["target_id"], set()).add(edge["source_id"])

    frontier = {origin_id}
    visited = {origin_id}
    predictions = []
    for hop_count in (1, 2):
        next_frontier = set()
        for current_id in frontier:
            next_frontier.update(neighbors.get(current_id, set()) - visited)
        for device_id in next_frontier:
            confidence = 0.42 if hop_count == 1 else 0.24
            predictions.append(
                (
                    event_id,
                    device_id,
                    hop_count,
                    confidence,
                    f"Dispositivo conectado por topología a {hop_count} salto(s); requiere evaluación.",
                )
            )
        visited.update(next_frontier)
        frontier = next_frontier

    connection.executemany(
        """
        INSERT INTO predictions (
            event_id, device_id, hop_count, confidence, reason
        ) VALUES (?, ?, ?, ?, ?)
        """,
        predictions,
    )


def degradation_for_device(
    history: list[sqlite3.Row],
) -> list[dict[str, str | float]]:
    if len(history) < 2:
        return []
    oldest, latest = history[0], history[-1]
    changes = []
    thresholds = {
        "latency_ms": 8,
        "packet_loss_pct": 1.5,
        "errors": 3,
    }
    for metric, threshold in thresholds.items():
        change = latest[metric] - oldest[metric]
        if change >= threshold:
            label, unit = METRIC_LABELS[metric]
            changes.append(
                {
                    "metric": label,
                    "change": round(change, 2),
                    "unit": unit,
                }
            )
    availability_drop = oldest["availability_pct"] - latest["availability_pct"]
    if availability_drop >= 1:
        changes.append(
            {
                "metric": "Disponibilidad",
                "change": round(availability_drop, 2),
                "unit": "puntos porcentuales de caída",
            }
        )
    return changes


def build_dashboard(path: Path = DATABASE_PATH) -> dict:
    initialize_database(path)
    now = datetime.now(timezone.utc)
    since = timestamp(now - timedelta(hours=24))

    with database(path) as connection:
        device_rows = connection.execute(
            "SELECT id, name, ip, type FROM devices ORDER BY name"
        ).fetchall()
        metrics_by_device = {}
        degradations = []
        latest_metrics = {}
        for device in device_rows:
            history = connection.execute(
                """
                SELECT * FROM metrics WHERE device_id = ?
                ORDER BY captured_at DESC, id DESC LIMIT 8
                """,
                (device["id"],),
            ).fetchall()
            history = list(reversed(history))
            if not history:
                continue
            latest = history[-1]
            latest_metrics[device["id"]] = latest
            changes = degradation_for_device(history)
            device_data = {
                "name": device["name"],
                "ip": device["ip"],
                "type": device["type"],
                "latencyMs": latest["latency_ms"],
                "packetLossPct": latest["packet_loss_pct"],
                "errors": int(latest["errors"]),
                "availabilityPct": latest["availability_pct"],
                "trafficMb": latest["traffic_mb"],
                "status": "Degradación" if changes else "Activo",
                "statusClass": "medium" if changes else "normal",
                "source": latest["source"],
            }
            metrics_by_device[device["id"]] = device_data
            if changes:
                degradations.append(
                    {
                        "device": device["name"],
                        "changes": changes,
                        "recommendation": (
                            "Comparar la tendencia con el historial y revisar "
                            "métricas del dispositivo."
                        ),
                    }
                )

        event_rows = connection.execute(
            """
            SELECT events.*, devices.name AS device, devices.ip
            FROM events JOIN devices ON devices.id = events.device_id
            ORDER BY events.captured_at DESC, events.id DESC LIMIT 25
            """
        ).fetchall()
        alerts = []
        for event in event_rows:
            event_data = {
                "id": event["id"],
                "device": event["device"],
                "ip": event["ip"],
                "capturedAt": event["captured_at"],
                "metric": event["metric"],
                "activity": event["activity"],
                "magnitude": event["magnitude"],
                "confidence": event["confidence"],
                "riskScore": event["risk_score"],
                "risk": event["risk_level"],
                "riskClass": risk_css_class(event["risk_level"]),
                "status": event["status"],
                "recommendation": event["recommendation"],
                "predictions": [
                    dict(prediction)
                    for prediction in connection.execute(
                        """
                        SELECT devices.name AS device, predictions.hop_count AS hops,
                               predictions.confidence, predictions.reason
                        FROM predictions
                        JOIN devices ON devices.id = predictions.device_id
                        WHERE predictions.event_id = ?
                        ORDER BY predictions.hop_count, devices.name
                        """,
                        (event["id"],),
                    ).fetchall()
                ],
            }
            alerts.append(event_data)

        recent_events = connection.execute(
            """
            SELECT risk_score, risk_level FROM events
            WHERE captured_at >= ? ORDER BY captured_at DESC, id DESC
            """,
            (since,),
        ).fetchall()
        average_event_risk = (
            statistics.fmean(event["risk_score"] for event in recent_events)
            if recent_events
            else 0
        )
        risk_index = min(
            100, round(average_event_risk * 0.75 + len(degradations) * 8)
        )
        risk_name = (
            "Elevado"
            if risk_index >= 65
            else "Moderado"
            if risk_index >= 35
            else "Bajo"
        )

        all_histories = []
        for device in device_rows:
            rows = connection.execute(
                """
                SELECT captured_at, traffic_mb FROM metrics
                WHERE device_id = ?
                ORDER BY captured_at DESC, id DESC LIMIT 6
                """,
                (device["id"],),
            ).fetchall()
            all_histories.append(list(reversed(rows)))
        traffic = []
        if all_histories:
            slot_count = max(map(len, all_histories))
            for slot in range(slot_count):
                samples = [
                    history[slot]
                    for history in all_histories
                    if len(history) == slot_count
                ]
                if samples:
                    capture_time = samples[-1]["captured_at"]
                    traffic.append(
                        {
                            "label": capture_time[11:16],
                            "value": round(
                                statistics.fmean(
                                    sample["traffic_mb"] for sample in samples
                                ),
                                2,
                            ),
                        }
                    )

        return {
            "generatedAt": timestamp(now),
            "mode": "simulado",
            "riskIndex": risk_index,
            "riskLevel": risk_name,
            "riskExplanation": (
                "Índice demostrativo: 75% del promedio de riesgo de anomalías "
                "recientes y 8 puntos por dispositivo con tendencia de degradación."
            ),
            "summary": {
                "monitoredDevices": len(device_rows),
                "anomalies": len(recent_events),
                "degradingDevices": len(degradations),
                "criticalRisks": sum(
                    event["risk_level"] == "Alto" for event in recent_events
                ),
            },
            "devices": list(metrics_by_device.values()),
            "degradations": degradations,
            "alerts": alerts,
            "traffic": traffic,
        }


def simulate_observation(path: Path = DATABASE_PATH) -> dict:
    initialize_database(path)
    with database(path) as connection:
        device = random.choice(
            connection.execute("SELECT id, name FROM devices").fetchall()
        )
        metric = random.choice(tuple(SCENARIOS))
        history = connection.execute(
            f"""
            SELECT {metric} FROM metrics WHERE device_id = ?
            ORDER BY captured_at DESC, id DESC LIMIT 12
            """,
            (device["id"],),
        ).fetchall()
        baseline_values = [row[metric] for row in history]
        baseline = statistics.fmean(baseline_values) if baseline_values else 0
        deviation = statistics.pstdev(baseline_values) if len(baseline_values) > 1 else 0
        scenario = SCENARIOS[metric]
        threshold = max(deviation * 2.5, scenario["minimum_delta"])
        increase = max(threshold * 2, scenario["minimum_delta"] * 2)
        if metric == "traffic_mb":
            increase = max(increase, baseline * 1.5)
        observed = baseline + increase
        anomaly_score = increase / max(deviation, scenario["minimum_delta"] / 2)
        confidence = min(
            0.97, 0.65 + max(0, anomaly_score - 2.5) * 0.035
        )
        risk_score = min(
            95,
            round(
                40
                + min(35, max(0, anomaly_score - 2.5) * 5)
                + scenario["impact"]
            ),
        )

        latest = connection.execute(
            """
            SELECT * FROM metrics WHERE device_id = ?
            ORDER BY captured_at DESC, id DESC LIMIT 1
            """,
            (device["id"],),
        ).fetchone()
        values = {column: latest[column] for column in METRIC_COLUMNS}
        values[metric] = round(observed, 2)
        captured_at = timestamp()
        connection.execute(
            """
            INSERT INTO metrics (
                device_id, captured_at, latency_ms, packet_loss_pct, errors,
                availability_pct, traffic_mb, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'simulado')
            """,
            (
                device["id"],
                captured_at,
                *(values[column] for column in METRIC_COLUMNS),
            ),
        )

        label, unit = METRIC_LABELS[metric]
        magnitude = (
            f"{label}: {round(observed, 2)} {unit} "
            f"(+{round(increase, 2)} sobre la línea base de "
            f"{round(baseline, 2)} {unit})"
        )
        event_id = insert_event(
            connection,
            device_id=device["id"],
            captured_at=captured_at,
            metric=metric,
            activity=scenario["activity"],
            magnitude=magnitude,
            confidence=round(confidence, 2),
            risk_score=risk_score,
            recommendation=scenario["recommendation"],
        )
        create_predictions(connection, event_id, device["id"])

        return {
            "eventId": event_id,
            "device": device["name"],
            "activity": scenario["activity"],
            "confidence": round(confidence, 2),
            "risk": risk_level(risk_score),
            "riskScore": risk_score,
            "message": "Se guardó una observación sintética para la demostración.",
        }


class NetGuardHandler(BaseHTTPRequestHandler):
    def send_json(self, status_code: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        if route == "/api/health":
            self.send_json(200, {"status": "ok", "mode": "simulado"})
            return
        if route == "/api/dashboard":
            try:
                self.send_json(200, build_dashboard())
            except (OSError, sqlite3.Error):
                logging.exception("No se pudo leer el dashboard de NetGuard AI")
                self.send_json(
                    500, {"error": "No fue posible leer los datos del dashboard."}
                )
            return
        self.send_json(404, {"error": "Ruta no encontrada."})

    def do_POST(self) -> None:
        route = urlsplit(self.path).path
        if route != "/api/simulate":
            self.send_json(404, {"error": "Ruta no encontrada."})
            return
        try:
            result = simulate_observation()
            self.send_json(201, result)
        except (OSError, sqlite3.Error):
            logging.exception("No se pudo guardar la observación simulada")
            self.send_json(
                500, {"error": "No fue posible guardar la observación simulada."}
            )

    def log_message(self, format_string: str, *args: object) -> None:
        logging.info("%s - %s", self.address_string(), format_string % args)


def main() -> None:
    initialize_database()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    server = ThreadingHTTPServer((HOST, PORT), NetGuardHandler)
    logging.info("API de demostración disponible en http://%s:%s", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Cerrando API de NetGuard AI")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
