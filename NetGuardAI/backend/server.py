import json
import logging
import os
import random
import socket
import sqlite3
import statistics
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Generator
from urllib.parse import urlsplit

if __package__:
    from .snmp_collector import SnmpConfigurationError, collect_devices
else:
    from snmp_collector import SnmpConfigurationError, collect_devices

try:
    import psycopg2
    from psycopg2.extras import DictCursor
except ImportError:
    psycopg2 = None
    DictCursor = None


DATABASE_PATH = Path(__file__).with_name("netguard.sqlite3")
DATABASE_URL = os.environ.get("DATABASE_URL")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
DATABASE_ERRORS = (sqlite3.Error,) + (
    (psycopg2.Error,) if psycopg2 is not None else ()
)

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


class DatabaseConnection:
    def __init__(
        self,
        connection: sqlite3.Connection | object,
        *,
        is_postgres: bool,
    ) -> None:
        self.connection = connection
        self.is_postgres = is_postgres

    def execute(self, query: str, parameters: tuple = ()):
        if self.is_postgres:
            cursor = self.connection.cursor(cursor_factory=DictCursor)
            cursor.execute(query.replace("?", "%s"), parameters)
            return cursor
        return self.connection.execute(query, parameters)

    def executemany(self, query: str, parameters):
        if self.is_postgres:
            cursor = self.connection.cursor(cursor_factory=DictCursor)
            cursor.executemany(query.replace("?", "%s"), parameters)
            return cursor
        return self.connection.executemany(query, parameters)

    def executescript(self, script: str) -> None:
        self.connection.executescript(script)

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


@contextmanager
def database(path: Path | None = None) -> Generator[DatabaseConnection, None, None]:
    use_postgres = path is None and bool(DATABASE_URL)
    if use_postgres:
        if psycopg2 is None:
            raise RuntimeError(
                "Se configuró DATABASE_URL, pero falta psycopg2. "
                "Instala las dependencias con «.venv/bin/python -m pip install -r requirements.txt»."
            )
        raw_connection = psycopg2.connect(DATABASE_URL)
        connection = DatabaseConnection(raw_connection, is_postgres=True)
    else:
        sqlite_path = path or DATABASE_PATH
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        raw_connection = sqlite3.connect(sqlite_path, timeout=5)
        raw_connection.row_factory = sqlite3.Row
        raw_connection.execute("PRAGMA foreign_keys = ON")
        connection = DatabaseConnection(raw_connection, is_postgres=False)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def timestamp(value: datetime | str | None = None) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
        return True


def get_available_port(start_port: int = PORT, *, host: str = HOST, max_tries: int = 25) -> int:
    for port in range(start_port, start_port + max_tries):
        if is_port_available(host, port):
            return port
    raise OSError(f"No se encontró un puerto disponible desde {start_port}.")


def initialize_database(path: Path | None = None) -> None:
    with database(path) as connection:
        schema = """
            CREATE TABLE IF NOT EXISTS devices (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                ip TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS topology (
                source_id BIGINT NOT NULL REFERENCES devices(id),
                target_id BIGINT NOT NULL REFERENCES devices(id),
                PRIMARY KEY (source_id, target_id),
                CHECK (source_id != target_id)
            );
            CREATE TABLE IF NOT EXISTS metrics (
                id BIGSERIAL PRIMARY KEY,
                device_id BIGINT NOT NULL REFERENCES devices(id),
                captured_at TIMESTAMPTZ NOT NULL,
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
                id BIGSERIAL PRIMARY KEY,
                device_id BIGINT NOT NULL REFERENCES devices(id),
                captured_at TIMESTAMPTZ NOT NULL,
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
                id BIGSERIAL PRIMARY KEY,
                event_id BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                device_id BIGINT NOT NULL REFERENCES devices(id),
                hop_count INTEGER NOT NULL,
                confidence REAL NOT NULL,
                reason TEXT NOT NULL,
                UNIQUE(event_id, device_id)
            );
            CREATE TABLE IF NOT EXISTS snmp_observations (
                id BIGSERIAL PRIMARY KEY,
                device_id BIGINT NOT NULL REFERENCES devices(id),
                captured_at TIMESTAMPTZ NOT NULL,
                uptime_ticks BIGINT NOT NULL,
                interfaces_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS snmp_observations_device_time
                ON snmp_observations(device_id, captured_at);
        """
        if connection.is_postgres:
            for statement in schema.split(";"):
                if statement.strip():
                    connection.execute(statement)
        else:
            connection.executescript(schema.replace("BIGSERIAL", "INTEGER").replace("BIGINT", "INTEGER").replace("TIMESTAMPTZ", "TEXT"))
        seed_database(connection)


def seed_database(connection: DatabaseConnection) -> None:
    for name, ip, device_type in DEVICES:
        existing_device = connection.execute(
            "SELECT id FROM devices WHERE name = ?", (name,)
        ).fetchone()
        if existing_device is None:
            connection.execute(
                "INSERT INTO devices (name, ip, type) VALUES (?, ?, ?)",
                (name, ip, device_type),
            )
    device_ids = {
        row["name"]: row["id"]
        for row in connection.execute("SELECT id, name FROM devices")
    }

    existing_topology = {
        (row["source_id"], row["target_id"])
        for row in connection.execute("SELECT source_id, target_id FROM topology")
    }
    missing_topology = [
        (device_ids[left], device_ids[right])
        for left, right in TOPOLOGY
        if (device_ids[left], device_ids[right]) not in existing_topology
    ]
    connection.executemany(
        "INSERT INTO topology (source_id, target_id) VALUES (?, ?)",
        missing_topology,
    )

    now = datetime.now(timezone.utc)
    metric_rows = []
    for device_name, measurements in SEED_METRICS.items():
        device_id = device_ids[device_name]
        has_metrics = connection.execute(
            "SELECT 1 FROM metrics WHERE device_id = ? LIMIT 1", (device_id,)
        ).fetchone()
        if has_metrics:
            continue
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

    event_count = connection.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    if event_count:
        return
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


def counter_delta(current: int | None, previous: int | None, modulus: int) -> int | None:
    if current is None or previous is None:
        return None
    return (current - previous) % modulus


def store_snmp_observations(
    results: list[dict], path: Path | None = None
) -> int:
    initialize_database(path)
    saved = 0
    with database(path) as connection:
        for result in results:
            if "error" in result:
                continue
            device = connection.execute(
                "SELECT id FROM devices WHERE ip = ?", (result["ip"],)
            ).fetchone()
            if device is None:
                query = (
                    "INSERT INTO devices (name, ip, type) VALUES (?, ?, ?) RETURNING id"
                    if connection.is_postgres
                    else "INSERT INTO devices (name, ip, type) VALUES (?, ?, ?)"
                )
                cursor = connection.execute(
                    query, (result["name"], result["ip"], result["type"])
                )
                device_id = (
                    cursor.fetchone()["id"]
                    if connection.is_postgres
                    else cursor.lastrowid
                )
            else:
                device_id = device["id"]

            previous = connection.execute(
                """
                SELECT captured_at, uptime_ticks, interfaces_json
                FROM snmp_observations
                WHERE device_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (device_id,),
            ).fetchone()
            captured_datetime = datetime.now(timezone.utc)
            interfaces = [dict(interface) for interface in result["interfaces"]]
            if previous:
                previous_datetime = previous["captured_at"]
                if isinstance(previous_datetime, str):
                    previous_datetime = datetime.fromisoformat(
                        previous_datetime.replace("Z", "+00:00")
                    )
                elapsed = (captured_datetime - previous_datetime).total_seconds()
                rebooted = result["uptimeTicks"] < previous["uptime_ticks"]
                old_interfaces = {
                    interface["index"]: interface
                    for interface in json.loads(previous["interfaces_json"])
                }
                for interface in interfaces:
                    old = old_interfaces.get(interface["index"])
                    if old is None or rebooted or elapsed <= 0:
                        interface["trafficMbPerMinute"] = None
                        interface["errorsSinceLast"] = None
                        interface["discardsSinceLast"] = None
                        continue
                    byte_delta = counter_delta(
                        interface["inOctets"], old["inOctets"], 2**64
                    )
                    outgoing_delta = counter_delta(
                        interface["outOctets"], old["outOctets"], 2**64
                    )
                    error_deltas = [
                        counter_delta(interface[key], old[key], 2**32)
                        for key in ("inErrors", "outErrors")
                    ]
                    discard_deltas = [
                        counter_delta(interface[key], old[key], 2**32)
                        for key in ("inDiscards", "outDiscards")
                    ]
                    interface["trafficMbPerMinute"] = (
                        round((byte_delta + outgoing_delta) * 60 / elapsed / 1_000_000, 2)
                        if byte_delta is not None and outgoing_delta is not None
                        else None
                    )
                    interface["errorsSinceLast"] = (
                        sum(error_deltas)
                        if all(value is not None for value in error_deltas)
                        else None
                    )
                    interface["discardsSinceLast"] = (
                        sum(discard_deltas)
                        if all(value is not None for value in discard_deltas)
                        else None
                    )
            else:
                for interface in interfaces:
                    interface["trafficMbPerMinute"] = None
                    interface["errorsSinceLast"] = None
                    interface["discardsSinceLast"] = None

            connection.execute(
                """
                INSERT INTO snmp_observations (
                    device_id, captured_at, uptime_ticks, interfaces_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    device_id,
                    timestamp(captured_datetime),
                    result["uptimeTicks"],
                    json.dumps(interfaces, ensure_ascii=False),
                ),
            )
            saved += 1
    return saved


def risk_level(score: int) -> str:
    if score >= 75:
        return "Alto"
    if score >= 50:
        return "Medio"
    return "Bajo"


def risk_css_class(level: str) -> str:
    return {"Alto": "high", "Medio": "medium", "Bajo": "normal"}[level]


def insert_event(
    connection: DatabaseConnection,
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
    query = """
        INSERT INTO events (
            device_id, captured_at, metric, activity, magnitude, confidence,
            risk_score, risk_level, recommendation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    parameters = (
        device_id,
        captured_at,
        metric,
        activity,
        magnitude,
        confidence,
        risk_score,
        risk_level(risk_score),
        recommendation,
    )
    if connection.is_postgres:
        cursor = connection.execute(f"{query.rstrip()} RETURNING id", parameters)
        return cursor.fetchone()["id"]
    cursor = connection.execute(query, parameters)
    return cursor.lastrowid


def create_predictions(
    connection: DatabaseConnection, event_id: int, origin_id: int
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


def build_dashboard(path: Path | None = None) -> dict:
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
                "capturedAt": timestamp(event["captured_at"]),
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
                            "label": timestamp(capture_time)[11:16],
                            "value": round(
                                statistics.fmean(
                                    sample["traffic_mb"] for sample in samples
                                ),
                                2,
                            ),
                        }
                    )

        snmp_rows = connection.execute(
            """
            SELECT devices.name, devices.ip, devices.type,
                       observations.captured_at, observations.uptime_ticks,
                       observations.interfaces_json
            FROM snmp_observations AS observations
            JOIN devices ON devices.id = observations.device_id
            JOIN (
                    SELECT device_id, MAX(id) AS latest_id
                    FROM snmp_observations
                    GROUP BY device_id
            ) AS latest ON latest.latest_id = observations.id
            ORDER BY devices.name
            """
        ).fetchall()
        snmp_devices = [
            {
                    "name": row["name"],
                    "ip": row["ip"],
                    "type": row["type"],
                    "capturedAt": timestamp(row["captured_at"]),
                    "uptimeSeconds": row["uptime_ticks"] // 100,
                    "interfaces": json.loads(row["interfaces_json"]),
            }
            for row in snmp_rows
        ]

        return {
            "generatedAt": timestamp(now),
            "mode": "simulado",
            "database": "PostgreSQL" if connection.is_postgres else "SQLite",
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
            "snmpDevices": snmp_devices,
        }


def simulate_observation(path: Path | None = None) -> dict:
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
            except (OSError, *DATABASE_ERRORS):
                logging.exception("No se pudo leer el dashboard de NetGuard AI")
                self.send_json(
                    500, {"error": "No fue posible leer los datos del dashboard."}
                )
            return
        self.send_json(404, {"error": "Ruta no encontrada."})

    def do_POST(self) -> None:
        route = urlsplit(self.path).path
        if route == "/api/snmp/poll":
            try:
                results = collect_devices()
                saved = store_snmp_observations(results)
                for result in results:
                    if "error" in result:
                        logging.warning(
                            "No se pudo consultar SNMPv3 en %s (%s): %s",
                            result["name"],
                            result["ip"],
                            result["error"],
                        )
                if saved == 0:
                    details = "; ".join(
                        f'{result["name"]}: {result["error"]}'
                        for result in results
                        if "error" in result
                    )
                    self.send_json(
                        502,
                        {
                            "error": (
                                "No se pudo consultar ninguno de los equipos SNMPv3. "
                                f"{details}"
                            ),
                            "results": results,
                        },
                    )
                else:
                    self.send_json(
                        200,
                        {
                            "saved": saved,
                            "results": results,
                        },
                    )
            except SnmpConfigurationError as error:
                self.send_json(400, {"error": str(error)})
            except (OSError, *DATABASE_ERRORS):
                logging.exception("No se pudieron guardar observaciones SNMPv3")
                self.send_json(
                    500, {"error": "No se pudieron guardar las observaciones SNMPv3."}
                )
            return
        if route != "/api/simulate":
            self.send_json(404, {"error": "Ruta no encontrada."})
            return
        try:
            result = simulate_observation()
            self.send_json(201, result)
        except (OSError, *DATABASE_ERRORS):
            logging.exception("No se pudo guardar la observación simulada")
            self.send_json(
                500, {"error": "No fue posible guardar la observación simulada."}
            )

    def log_message(self, format_string: str, *args: object) -> None:
        logging.info("%s - %s", self.address_string(), format_string % args)


def main() -> None:
    initialize_database()
    resolved_port = get_available_port(PORT, host=HOST)
    os.environ["PORT"] = str(resolved_port)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    server = ThreadingHTTPServer((HOST, resolved_port), NetGuardHandler)
    logging.info("API de demostración disponible en http://%s:%s", HOST, resolved_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Cerrando API de NetGuard AI")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
