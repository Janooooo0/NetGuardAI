import unittest

from backend.ping_collector import parse_ping_output

ES_OK = """Haciendo ping a 10.0.0.5 con 32 bytes de datos:
Respuesta desde 10.0.0.5: bytes=32 tiempo<1m TTL=128
Respuesta desde 10.0.0.5: bytes=32 tiempo=3ms TTL=128

Estadísticas de ping para 10.0.0.5:
    Paquetes: enviados = 2, recibidos = 2, perdidos = 0
"""
EN_UNREACHABLE = """Pinging 10.0.0.9 with 32 bytes of data:
Reply from 10.0.0.1: Destination host unreachable.
Request timed out.

Ping statistics for 10.0.0.9:
    Packets: Sent = 2, Received = 1, Lost = 1 (50% loss),
"""


class WindowsPingParserTests(unittest.TestCase):
    def test_spanish_output(self):
        m = parse_ping_output(ES_OK)
        self.assertEqual((m.sent, m.received, m.packet_loss_pct), (2, 2, 0.0))
        self.assertEqual(m.latency_ms, 2.0)

    def test_unreachable_is_not_counted_as_reply(self):
        m = parse_ping_output(EN_UNREACHABLE)
        self.assertEqual((m.received, m.packet_loss_pct, m.latency_ms), (0, 100.0, None))


if __name__ == "__main__":
    unittest.main()
