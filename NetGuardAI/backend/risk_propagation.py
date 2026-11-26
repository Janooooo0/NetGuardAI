"""Predicción de riesgos por propagación en la topología de red.

Cuando se confirma una anomalía en un dispositivo, se recorre la topología
(grafo no dirigido construido con la columna ``uplink`` del inventario)
mediante búsqueda en anchura (BFS) y se marcan como *potencialmente
afectados* los dispositivos alcanzables a pocos saltos. La confianza decae
con la distancia: ``confianza = confianza_evento * DECAY ** saltos``.
No se afirma compromiso: solo se estima exposición por cercanía.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

MAX_HOPS = 3
CONFIDENCE_DECAY = 0.7
MIN_CONFIDENCE = 0.15
EVENT_DEDUP_WINDOW = timedelta(minutes=30)


def build_adjacency(edges: Iterable[tuple[int, int]]) -> dict[int, set[int]]:
    adjacency: dict[int, set[int]] = {}
    for source, target in edges:
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    return adjacency


def predict_affected(
    adjacency: dict[int, set[int]],
    origin: int,
    base_confidence: float,
    *,
    max_hops: int = MAX_HOPS,
    decay: float = CONFIDENCE_DECAY,
    min_confidence: float = MIN_CONFIDENCE,
) -> list[tuple[int, int, float]]:
    """Devuelve [(device_id, saltos, confianza)] ordenado por saltos."""
    visited = {origin}
    queue: deque[tuple[int, int]] = deque([(origin, 0)])
    affected: list[tuple[int, int, float]] = []
    while queue:
        node, hops = queue.popleft()
        if hops >= max_hops:
            continue
        for neighbor in sorted(adjacency.get(node, ())):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            confidence = round(base_confidence * decay ** (hops + 1), 3)
            if confidence < min_confidence:
                continue
            affected.append((neighbor, hops + 1, confidence))
            queue.append((neighbor, hops + 1))
    return affected


def risk_level_for(score: int) -> str:
    return "Alto" if score >= 75 else "Medio" if score >= 50 else "Bajo"


def record_risk_event(
    connection: Any,
    *,
    device_id: int,
    captured_at: str,
    metric: str,
    activity: str,
    magnitude: str,
    confidence: float,
    risk_score: int,
    recommendation: str,
) -> int | None:
    """Registra un evento y sus predicciones. Devuelve el id o None si duplicado."""
    since = (datetime.now(timezone.utc) - EVENT_DEDUP_WINDOW).isoformat().replace(
        "+00:00", "Z"
    )
    duplicate = connection.execute(
        "SELECT id FROM events WHERE device_id = ? AND metric = ? AND captured_at >= ?",
        (device_id, metric, since),
    ).fetchone()
    if duplicate is not None:
        return None

    level = risk_level_for(risk_score)
    if connection.is_postgres:
        row = connection.execute(
            """
            INSERT INTO events (device_id, captured_at, metric, activity, magnitude,
                                confidence, risk_score, risk_level, recommendation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
            """,
            (device_id, captured_at, metric, activity, magnitude,
             confidence, risk_score, level, recommendation),
        ).fetchone()
        event_id = row["id"]
    else:
        connection.execute(
            """
            INSERT INTO events (device_id, captured_at, metric, activity, magnitude,
                                confidence, risk_score, risk_level, recommendation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (device_id, captured_at, metric, activity, magnitude,
             confidence, risk_score, level, recommendation),
        )
        event_id = connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    edges = [
        (row["source_id"], row["target_id"])
        for row in connection.execute("SELECT source_id, target_id FROM topology").fetchall()
    ]
    origin_name = connection.execute(
        "SELECT name FROM devices WHERE id = ?", (device_id,)
    ).fetchone()["name"]
    for affected_id, hops, affected_confidence in predict_affected(
        build_adjacency(edges), device_id, confidence
    ):
        connection.execute(
            """
            INSERT INTO predictions (event_id, device_id, hop_count, confidence, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_id,
                affected_id,
                hops,
                affected_confidence,
                f"Conectado a {hops} salto(s) de {origin_name}, donde se detectó "
                f"{activity.lower()}. Exposición estimada, no compromiso confirmado.",
            ),
        )
    return event_id
