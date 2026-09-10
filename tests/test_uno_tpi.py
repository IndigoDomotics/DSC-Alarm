import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]
MODULE_PATH = (
    ROOT
    / "DSC Alarm.indigoPlugin"
    / "Contents"
    / "Server Plugin"
    / "uno_tpi.py"
)
SPEC = importlib.util.spec_from_file_location("uno_tpi", MODULE_PATH)
uno_tpi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(uno_tpi)


class UnoDecoderTests(unittest.TestCase):
    def test_parse_hex_bytes_ignores_separators(self):
        self.assertEqual([0x01, 0xA2, 0xFF], uno_tpi.parse_hex_bytes("01 A2-FF"))

    def test_decode_bitfield_numbers_bits_from_one(self):
        self.assertEqual(
            {1: True, 2: False, 3: True, 4: False},
            uno_tpi.decode_bitfield("05", 4),
        )

    def test_decode_partitions(self):
        client = uno_tpi.UnoTpiClient("example.invalid", "secret")
        self.assertEqual(
            {1: "ready", 2: "armedStay", 3: "alarm", 4: "busy"},
            client.decode_partitions("010411FF"),
        )

    def test_extracts_host_frames_and_ack_from_partial_input(self):
        client = uno_tpi.UnoTpiClient("example.invalid", "secret")
        client._rxbuf = "noise%01,05$^0C,00$tail%02,01"
        events = client._extract_events()
        self.assertEqual(["zones", "ack"], [event.kind for event in events])
        self.assertTrue(events[0].data[1])
        self.assertTrue(events[0].data[3])
        self.assertEqual({"cmd": "0C", "code": 0}, events[1].data)
        self.assertEqual("tail%02,01", client._rxbuf)
        client._rxbuf += "$"
        events = client._extract_events()
        self.assertEqual(["partitions"], [event.kind for event in events])
        self.assertEqual({1: "ready"}, events[0].data)
        self.assertEqual("", client._rxbuf)

    def test_command_format_and_validation(self):
        client = uno_tpi.UnoTpiClient("example.invalid", "secret")
        sent = []
        client._send_raw = sent.append
        client.send_command("0a", "02")
        self.assertEqual(["^0A,02$\r\n"], sent)
        with self.assertRaises(ValueError):
            client.send_command("bad")

    def test_temperature_and_timer_decoding(self):
        self.assertEqual({1: None, 2: 0.0, 3: 20.0}, uno_tpi.decode_zone_temperatures("005078"))
        self.assertEqual({1: 1, 2: 258}, uno_tpi.decode_zone_timers("01000201"))


if __name__ == "__main__":
    unittest.main()
