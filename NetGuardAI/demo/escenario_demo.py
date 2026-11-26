r"""Escenario de demostración: genera observaciones simuladas y ejecuta el
pipeline real de NetGuard AI (detección -> evento -> predicción por topología).

Uso (desde la raíz del proyecto):
    python demo/escenario_demo.py
    set NETGUARD_INVENTORY=demo\inventario_demo.csv & set NETGUARD_DB_PATH=demo\netguard_demo.sqlite3 & npm run dev
"""
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ["NETGUARD_INVENTORY"] = str(ROOT / "inventario_demo.csv")
os.environ["NETGUARD_DB_PATH"] = str(ROOT / "netguard_demo.sqlite3")
sys.path.insert(0, str(ROOT.parent / "backend"))
db = Path(os.environ["NETGUARD_DB_PATH"])
if db.exists():
    db.unlink()

import server  # noqa: E402
from ping_collector import PingMeasurement, PingTarget  # noqa: E402

server.initialize_database()
now = datetime.now(timezone.utc)

# 1) Ping: todos responden; PC-Ventas pierde conectividad total.
for ip in ["192.168.10.1", "192.168.10.2", "192.168.10.20", "192.168.10.30"]:
    server.store_ping_observation(PingTarget(ip, ip), PingMeasurement(4, 4, 2.1, 0.0))
server.store_ping_observation(
    PingTarget("192.168.10.22", "192.168.10.22"), PingMeasurement(4, 0, None, 100.0)
)

# 2) SNMP: Switch-Piso2 pasa de ~10 MB/min a ~35 MB/min sostenido.
with server.database() as c:
    dev = c.execute("SELECT id FROM devices WHERE ip='192.168.10.3'").fetchone()["id"]
    for minutes, rate in [(25, 10.0), (20, 10.4), (15, 34.0), (10, 36.5), (5, 35.2)]:
        iface = [{"index": 1, "name": "GigabitEthernet0/1", "trafficMbPerMinute": rate,
                  "inOctets": 0, "outOctets": 0, "inErrors": 0, "outErrors": 0,
                  "inDiscards": 0, "outDiscards": 0}]
        c.execute(
            "INSERT INTO snmp_observations (device_id, captured_at, uptime_ticks, interfaces_json)"
            " VALUES (?, ?, ?, ?)",
            (dev, server.timestamp(now - timedelta(minutes=minutes)), 100000, json.dumps(iface)),
        )
    server.evaluate_snmp_anomaly(c, dev, now)

d = server.build_dashboard()
print("Risk Index:", d["riskIndex"], d["riskLevel"])
for a in d["alerts"]:
    print(f"- {a['device']} ({a['ip']}): {a['activity']} | {a['magnitude']} | riesgo {a['risk']}")
    for p in a["predictions"]:
        print(f"    -> {p['device']}: {p['hops']} salto(s), confianza {p['confidence']:.0%}")
