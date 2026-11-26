import asyncio
import ipaddress
import json
import os
from dataclasses import dataclass
from typing import Any
try:
    from .crypto_vault import VaultError, reveal
except ImportError:
    from crypto_vault import VaultError, reveal


class SnmpConfigurationError(ValueError):
    pass


class SnmpCollectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnmpDevice:
    name: str
    ip: str
    device_type: str


@dataclass(frozen=True)
class SnmpCredentials:
    username: str
    auth_password: str
    privacy_password: str
    auth_protocol: str
    privacy_protocol: str


def load_devices(value: str | None = None) -> list[SnmpDevice]:
    raw_devices = value if value is not None else os.environ.get("SNMP_DEVICES", "")
    if not raw_devices:
        raise SnmpConfigurationError(
            "Configura SNMP_DEVICES con los equipos autorizados del laboratorio."
        )
    try:
        parsed = json.loads(raw_devices)
    except json.JSONDecodeError as error:
        raise SnmpConfigurationError("SNMP_DEVICES debe ser una lista JSON válida.") from error
    if not isinstance(parsed, list) or not parsed:
        raise SnmpConfigurationError(
            "SNMP_DEVICES debe contener al menos un equipo autorizado."
        )

    devices = []
    seen_ips = set()
    for item in parsed:
        if not isinstance(item, dict):
            raise SnmpConfigurationError("Cada equipo SNMP debe ser un objeto JSON.")
        name, ip, device_type = (
            item.get("name"),
            item.get("ip"),
            item.get("type", "Equipo de laboratorio"),
        )
        if not isinstance(name, str) or not name.strip():
            raise SnmpConfigurationError("Cada equipo SNMP necesita un nombre.")
        if not isinstance(ip, str):
            raise SnmpConfigurationError(f"El equipo {name} necesita una dirección IP.")
        try:
            address = ipaddress.ip_address(ip)
        except ValueError as error:
            raise SnmpConfigurationError(f"IP inválida para el equipo {name}.") from error
        if (
            address.version != 4
            or not address.is_private
            or address.is_loopback
            or address.is_link_local
        ):
            raise SnmpConfigurationError(
                f"El equipo {name} debe usar una IPv4 privada del laboratorio."
            )
        if ip in seen_ips:
            raise SnmpConfigurationError("Cada equipo debe tener una IP distinta.")
        if not isinstance(device_type, str):
            raise SnmpConfigurationError(f"Tipo inválido para el equipo {name}.")
        seen_ips.add(ip)
        devices.append(SnmpDevice(name.strip(), ip, device_type.strip()))
    return devices


def load_credentials() -> SnmpCredentials:
    username = os.environ.get("SNMPV3_USERNAME", "")
    try:
        auth_password = reveal(os.environ.get("SNMPV3_AUTH_PASSWORD", ""))
        privacy_password = reveal(os.environ.get("SNMPV3_PRIV_PASSWORD", ""))
    except VaultError as error:
        raise SnmpConfigurationError(f"Credenciales SNMPv3 cifradas: {error}") from error
    auth_protocol = os.environ.get("SNMPV3_AUTH_PROTOCOL", "SHA").upper()
    privacy_protocol = os.environ.get("SNMPV3_PRIV_PROTOCOL", "AES-128").upper()
    if not username:
        raise SnmpConfigurationError("Falta configurar SNMPV3_USERNAME.")
    if len(auth_password) < 8 or len(privacy_password) < 8:
        raise SnmpConfigurationError(
            "Las claves SNMPv3 de autenticación y privacidad deben tener al menos 8 caracteres."
        )
    if auth_protocol not in {"SHA", "SHA-256"}:
        raise SnmpConfigurationError("SNMPV3_AUTH_PROTOCOL admite SHA o SHA-256.")
    if privacy_protocol != "AES-128":
        raise SnmpConfigurationError("SNMPV3_PRIV_PROTOCOL debe ser AES-128.")
    return SnmpCredentials(
        username,
        auth_password,
        privacy_password,
        auth_protocol,
        privacy_protocol,
    )


def _pysnmp() -> Any:
    try:
        from pysnmp.hlapi.v3arch import asyncio as hlapi
    except ImportError as error:
        raise SnmpConfigurationError(
            "Falta PySNMP; instala las dependencias con "
            "«.venv/bin/python -m pip install -r requirements.txt»."
        ) from error
    return hlapi


async def _walk_column(
    hlapi: Any,
    engine: Any,
    auth: Any,
    target: Any,
    root_oid: str,
    *,
    text_values: bool = False,
) -> dict[int, int | str]:
    values = {}
    async for indication, status, index, bindings in hlapi.walk_cmd(
        engine,
        auth,
        target,
        hlapi.ContextData(),
        hlapi.ObjectType(hlapi.ObjectIdentity(root_oid)),
        lexicographicMode=False,
    ):
        if indication:
            raise SnmpCollectionError(str(indication))
        if status:
            raise SnmpCollectionError(
                f"SNMP devolvió {status.prettyPrint()} en la variable {index}."
            )
        for oid, value in bindings:
            suffix = str(oid).removeprefix(f"{root_oid}.")
            try:
                interface_index = int(suffix)
            except ValueError:
                continue
            values[interface_index] = str(value) if text_values else int(value)
    return values


async def _poll_device(
    device: SnmpDevice, credentials: SnmpCredentials
) -> dict[str, Any]:
    hlapi = _pysnmp()
    if credentials.auth_protocol == "SHA-256":
        auth_protocol = hlapi.usmHMAC192SHA256AuthProtocol
    else:
        auth_protocol = hlapi.usmHMACSHAAuthProtocol
    auth = hlapi.UsmUserData(
        credentials.username,
        credentials.auth_password,
        credentials.privacy_password,
        authProtocol=auth_protocol,
        privProtocol=hlapi.usmAesCfb128Protocol,
    )
    engine = hlapi.SnmpEngine()
    try:
        target = await hlapi.UdpTransportTarget.create(
            (device.ip, 161), timeout=1, retries=1
        )
        indication, status, index, bindings = await hlapi.get_cmd(
            engine,
            auth,
            target,
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.2.1.1.3.0")),
        )
        if indication:
            raise SnmpCollectionError(str(indication))
        if status:
            raise SnmpCollectionError(
                f"SNMP devolvió {status.prettyPrint()} en la variable {index}."
            )
        uptime_ticks = int(bindings[0][1])

        roots = {
            "name": "1.3.6.1.2.1.31.1.1.1.1",
            "status": "1.3.6.1.2.1.2.2.1.8",
            "in_octets": "1.3.6.1.2.1.31.1.1.1.6",
            "out_octets": "1.3.6.1.2.1.31.1.1.1.10",
            "in_errors": "1.3.6.1.2.1.2.2.1.14",
            "out_errors": "1.3.6.1.2.1.2.2.1.20",
            "in_discards": "1.3.6.1.2.1.2.2.1.13",
            "out_discards": "1.3.6.1.2.1.2.2.1.19",
        }
        columns = {}
        for key, oid in roots.items():
            columns[key] = await _walk_column(
                hlapi, engine, auth, target, oid, text_values=key == "name"
            )
        interfaces = [
            {
                "index": interface_index,
                "name": name,
                "status": columns["status"].get(interface_index),
                "inOctets": columns["in_octets"].get(interface_index),
                "outOctets": columns["out_octets"].get(interface_index),
                "inErrors": columns["in_errors"].get(interface_index),
                "outErrors": columns["out_errors"].get(interface_index),
                "inDiscards": columns["in_discards"].get(interface_index),
                "outDiscards": columns["out_discards"].get(interface_index),
            }
            for interface_index, name in sorted(columns["name"].items())
        ]
        if not interfaces:
            raise SnmpCollectionError("El agente no devolvió interfaces IF-MIB.")
        return {
            "name": device.name,
            "ip": device.ip,
            "type": device.device_type,
            "uptimeTicks": uptime_ticks,
            "uptimeSeconds": uptime_ticks // 100,
            "interfaces": interfaces,
        }
    finally:
        engine.close_dispatcher()


async def _collect(
    devices: list[SnmpDevice], credentials: SnmpCredentials
) -> list[dict[str, Any]]:
    results = []
    for device in devices:
        try:
            results.append(await _poll_device(device, credentials))
        except (SnmpCollectionError, OSError, TypeError, ValueError) as error:
            results.append(
                {
                    "name": device.name,
                    "ip": device.ip,
                    "error": str(error),
                }
            )
    return results


def collect_devices() -> list[dict[str, Any]]:
    devices = load_devices()
    credentials = load_credentials()
    return asyncio.run(_collect(devices, credentials))
