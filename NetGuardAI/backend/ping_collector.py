import ipaddress
import json
import os
import re
import subprocess
from dataclasses import dataclass


PING_COUNT = 5
PING_TIMEOUT_SECONDS = 1


class PingConfigurationError(ValueError):
    pass


class PingProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class PingTarget:
    device_ip: str
    target_ip: str


@dataclass(frozen=True)
class PingMeasurement:
    sent: int
    received: int
    latency_ms: float | None
    packet_loss_pct: float


def _private_ipv4(value: str, label: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise PingConfigurationError(f"{label} no es una dirección IP válida.") from error
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
    ):
        raise PingConfigurationError(f"{label} debe ser una IPv4 privada.")
    return str(address)


def load_ping_targets(
    inventory_ips: set[str], value: str | None = None
) -> list[PingTarget]:
    raw_targets = value if value is not None else os.environ.get("PING_TARGETS", "")
    if not raw_targets:
        raise PingConfigurationError(
            "Configura PING_TARGETS con los destinos privados autorizados."
        )
    try:
        parsed = json.loads(raw_targets)
    except json.JSONDecodeError as error:
        raise PingConfigurationError("PING_TARGETS debe ser una lista JSON válida.") from error
    if not isinstance(parsed, list) or not parsed:
        raise PingConfigurationError("PING_TARGETS debe contener al menos un destino.")

    targets = []
    seen_devices = set()
    for item in parsed:
        if not isinstance(item, dict):
            raise PingConfigurationError("Cada destino de ping debe ser un objeto JSON.")
        device_ip = item.get("device_ip")
        target_ip = item.get("target_ip")
        if not isinstance(device_ip, str) or not isinstance(target_ip, str):
            raise PingConfigurationError(
                "Cada destino de ping necesita device_ip y target_ip."
            )
        device_ip = _private_ipv4(device_ip, "device_ip")
        target_ip = _private_ipv4(target_ip, "target_ip")
        if device_ip not in inventory_ips:
            raise PingConfigurationError(
                f"El dispositivo {device_ip} no está incluido en laptop.csv."
            )
        if device_ip in seen_devices:
            raise PingConfigurationError(
                "Cada dispositivo debe tener un único destino de ping."
            )
        seen_devices.add(device_ip)
        targets.append(PingTarget(device_ip, target_ip))
    return targets


def load_ping_interval(value: str | None = None) -> int:
    raw_interval = (
        value if value is not None else os.environ.get("PING_INTERVAL_SECONDS", "60")
    )
    try:
        interval = int(raw_interval)
    except ValueError as error:
        raise PingConfigurationError(
            "PING_INTERVAL_SECONDS debe ser un número entero."
        ) from error
    if not 30 <= interval <= 3600:
        raise PingConfigurationError(
            "PING_INTERVAL_SECONDS debe estar entre 30 y 3600 segundos."
        )
    return interval


def parse_ping_output(output: str) -> PingMeasurement:
    statistics_match = re.search(
        r"(?m)^\s*(\d+)\s+packets transmitted,\s*(\d+)\s+"
        r"(?:packets?\s+)?received\b",
        output,
    )
    if statistics_match is None:
        raise PingProbeError("ping no devolvió estadísticas de paquetes.")

    sent, received = map(int, statistics_match.groups())
    if sent <= 0 or received > sent:
        raise PingProbeError("ping devolvió contadores de paquetes inválidos.")

    latency_match = re.search(
        r"(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s*=\s*"
        r"[^/]+/([0-9]+(?:\.[0-9]+)?)/",
        output,
    )
    latency_ms = float(latency_match.group(1)) if latency_match else None
    packet_loss_pct = round((sent - received) / sent * 100, 2)
    return PingMeasurement(sent, received, latency_ms, packet_loss_pct)


def probe_ping(target_ip: str) -> PingMeasurement:
    target_ip = _private_ipv4(target_ip, "target_ip")
    timeout = PING_COUNT * PING_TIMEOUT_SECONDS + 3
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        result = subprocess.run(
            [
                "ping",
                "-n",
                "-c",
                str(PING_COUNT),
                "-W",
                str(PING_TIMEOUT_SECONDS),
                "-w",
                str(timeout - 2),
                target_ip,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise PingProbeError("La consulta ICMP excedió el tiempo máximo.") from error

    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode not in {0, 1}:
        raise PingProbeError(
            f"ping terminó con estado {result.returncode}."
        )
    return parse_ping_output(output)
