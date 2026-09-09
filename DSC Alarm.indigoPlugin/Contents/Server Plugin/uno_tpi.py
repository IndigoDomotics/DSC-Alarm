# -*- coding: utf-8 -*-
"""EyezOn UNO TPI backend for the Indigo DSC Alarm plugin.

This module is intentionally separate from the DSC/EnvisaLink parser.  It
connects to a UNO panel on TCP 4025, parses %xx,...$ host frames, and exposes
simple normalized events for plugin.py.
"""

import re
import socket
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

UNO_DEFAULT_PORT = 4025


@dataclass
class UnoEvent:
    kind: str
    data: object
    raw_cmd: str = ""
    raw_data: str = ""


class UnoTpiError(Exception):
    pass


class UnoTpiClient:
    FRAME_RE = re.compile(r"%([0-9A-Fa-f]{2}),(.*?)\$", re.S)
    ACK_RE = re.compile(r"\^([0-9A-Fa-f]{2}),([0-9A-Fa-f]{1,2})\$", re.S)

    PARTITION_STATE_MAP = {
        0x00: "unused",
        0x01: "ready",
        0x02: "readyBypassed",
        0x03: "notReady",
        0x04: "armedStay",
        0x05: "armedAway",
        0x08: "exitDelay",
        0x09: "armedAwayNoEntryDelay",
        0x0C: "entryDelay",
        0x11: "alarm",
    }

    def __init__(self, host: str, password: str, port: int = UNO_DEFAULT_PORT, timeout: float = 1.0, logger=None):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout
        self.logger = logger
        self.sock: Optional[socket.socket] = None
        self._rxbuf = ""

    def connect(self) -> None:
        self.close()
        s = socket.create_connection((self.host, self.port), timeout=10.0)
        s.settimeout(self.timeout)
        self.sock = s
        banner = self._recv_until_any(("Login:", "login:", "LOGIN:"), timeout=10.0)
        if "login" not in banner.lower():
            raise UnoTpiError(f"UNO did not present Login prompt; got {banner!r}")
        self._send_raw(self.password + "\r")
        reply = self._recv_until_any(("OK", "FAILED", "Timed Out", "Timed out"), timeout=10.0)
        if "OK" in reply:
            return
        if "FAILED" in reply:
            raise UnoTpiError("UNO rejected login password")
        if "timed out" in reply.lower():
            raise UnoTpiError("UNO login timed out")
        raise UnoTpiError(f"Unexpected UNO login response: {reply!r}")

    def is_connected(self) -> bool:
        return self.sock is not None

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _send_raw(self, text: str) -> None:
        if not self.sock:
            raise UnoTpiError("UNO socket is not connected")
        self.sock.sendall(text.encode("ascii"))

    def _recv_some(self) -> str:
        if not self.sock:
            raise UnoTpiError("UNO socket is not connected")
        data = self.sock.recv(4096)
        if not data:
            raise UnoTpiError("UNO socket closed")
        return data.decode("ascii", errors="replace")

    def _recv_until_any(self, needles: Tuple[str, ...], timeout: float) -> str:
        if not self.sock:
            raise UnoTpiError("UNO socket is not connected")
        old_timeout = self.sock.gettimeout()
        self.sock.settimeout(timeout)
        out = ""
        try:
            end = time.time() + timeout
            while time.time() < end:
                try:
                    out += self._recv_some()
                except socket.timeout:
                    pass
                if any(n in out for n in needles):
                    return out
        finally:
            self.sock.settimeout(old_timeout)
        return out

    def send_command(self, cmd_hex: str, data: str = "") -> None:
        cmd_hex = cmd_hex.upper()
        if not re.match(r"^[0-9A-F]{2}$", cmd_hex):
            raise ValueError("cmd_hex must be two hex digits")
        frame = f"^{cmd_hex},{data}$\r\n"
        if self.logger:
            self.logger.threaddebug(f"UNO TX: {frame.strip()}")
        self._send_raw(frame)

    def poll(self) -> None:
        self.send_command("00", "")

    def request_initial_state_dump(self) -> None:
        self.send_command("0C", "")

    def request_host_information(self) -> None:
        self.send_command("0D", "")

    def stay_arm_partition(self, partition: int) -> None:
        self.send_command("08", str(int(partition)))

    def away_arm_partition(self, partition: int) -> None:
        self.send_command("09", str(int(partition)))

    def disarm_partition(self, partition: int, code: str) -> None:
        self.send_command("12", f"{int(partition)},{code}")

    def bypass_zone(self, zone: int) -> None:
        self.send_command("04", f"{int(zone):03d}")

    def unbypass_zone(self, zone: int) -> None:
        self.send_command("05", f"{int(zone):03d}")

    def toggle_pgm(self, pgm: int) -> None:
        self.send_command("0A", f"{int(pgm):02d}")

    def read_events(self) -> List[UnoEvent]:
        try:
            self._rxbuf += self._recv_some()
        except socket.timeout:
            return []
        return self._extract_events()

    def _extract_events(self) -> List[UnoEvent]:
        events: List[UnoEvent] = []
        while True:
            m = self.FRAME_RE.search(self._rxbuf)
            a = self.ACK_RE.search(self._rxbuf)
            candidates = [x for x in (m, a) if x is not None]
            if not candidates:
                if len(self._rxbuf) > 2048:
                    self._rxbuf = self._rxbuf[-256:]
                break
            first = min(candidates, key=lambda x: x.start())
            if first.start() > 0:
                self._rxbuf = self._rxbuf[first.start():]
            if self._rxbuf.startswith("%"):
                m = self.FRAME_RE.match(self._rxbuf)
                if not m:
                    break
                cmd, data = m.group(1).upper(), m.group(2)
                if self.logger:
                    self.logger.threaddebug(f"UNO RX: %{cmd},{data}$")
                events.extend(self._decode_host_frame(cmd, data))
                self._rxbuf = self._rxbuf[m.end():]
            elif self._rxbuf.startswith("^"):
                a = self.ACK_RE.match(self._rxbuf)
                if not a:
                    break
                cmd, code = a.group(1).upper(), int(a.group(2), 16)
                events.append(UnoEvent("ack", {"cmd": cmd, "code": code}, cmd, str(code)))
                self._rxbuf = self._rxbuf[a.end():]
            else:
                break
        return events

    def _decode_host_frame(self, cmd: str, data: str) -> List[UnoEvent]:
        if cmd == "01":
            return [UnoEvent("zones", decode_bitfield(data, 128), cmd, data)]
        if cmd == "02":
            return [UnoEvent("partitions", self.decode_partitions(data), cmd, data)]
        if cmd == "03":
            return [UnoEvent("cid", decode_cid(data), cmd, data)]
        if cmd == "04":
            return [UnoEvent("bypass", decode_bitfield(data, 128), cmd, data)]
        if cmd == "05":
            return [UnoEvent("host", decode_host_info(data), cmd, data)]
        if cmd == "06":
            return [UnoEvent("troubles", self.decode_troubles(data), cmd, data)]
        if cmd == "07":
            return [UnoEvent("zone_temperatures", decode_zone_temperatures(data), cmd, data)]
        if cmd == "08":
            return [UnoEvent("partition_temperatures", decode_partition_temperatures(data), cmd, data)]
        if cmd == "09":
            return [UnoEvent("keypad_one_time_sound", decode_keypad_one_time_sound(data), cmd, data)]
        if cmd == "0A":
            return [UnoEvent("keypad_persistent_sound", decode_keypad_persistent_sound(data), cmd, data)]
        if cmd == "10":
            return [UnoEvent("partition_chime", decode_partition_chime(data), cmd, data)]
        if cmd == "FF":
            return [UnoEvent("zone_timers", decode_zone_timers(data), cmd, data)]
        return [UnoEvent("unknown", data, cmd, data)]

    def decode_partitions(self, hexstr: str) -> Dict[int, str]:
        out = {}
        for i, b in enumerate(parse_hex_bytes(hexstr)[:8], start=1):
            out[i] = self.PARTITION_STATE_MAP.get(b, "busy")
        return out

    def decode_troubles(self, hexstr: str) -> Dict[int, List[str]]:
        labels = [
            "serviceRequired", "acFailure", "wirelessLowBattery", "serverOffline",
            "zoneTrouble", "systemBatteryOvercurrent", "bellSirenFault", "wirelessSupervisoryFault",
        ]
        out = {}
        for i, b in enumerate(parse_hex_bytes(hexstr)[:8], start=1):
            out[i] = [labels[bit] for bit in range(8) if b & (1 << bit)]
        return out


def parse_hex_bytes(hexstr: str) -> List[int]:
    hexstr = re.sub(r"[^0-9A-Fa-f]", "", hexstr)
    return [int(hexstr[i:i + 2], 16) for i in range(0, len(hexstr), 2)]


def decode_bitfield(hexstr: str, max_bits: int) -> Dict[int, bool]:
    out = {}
    for byte_index, b in enumerate(parse_hex_bytes(hexstr)):
        for bit in range(8):
            item = byte_index * 8 + bit + 1
            if item <= max_bits:
                out[item] = bool(b & (1 << bit))
    return out


def decode_host_info(data: str) -> Dict[str, str]:
    parts = data.split(",")
    return {
        "mac": parts[0] if len(parts) > 0 else "",
        "type": parts[1].strip() if len(parts) > 1 else "",
        "version": parts[2].strip() if len(parts) > 2 else "",
        "default_partition": parts[3].strip() if len(parts) > 3 else "",
        "time": parts[4].strip() if len(parts) > 4 else "",
    }


def decode_cid(data: str) -> Dict[str, str]:
    return {
        "qualifier": data[0:1],
        "event_code": data[1:4],
        "partition": data[4:6],
        "zone_or_user": data[6:9],
        "padding": data[9:10],
        "raw": data,
    }


def decode_keypad_one_time_sound(data: str) -> Dict[str, object]:
    """Decode UNO %09 keypad one-time sound frame.

    Observed example: %09,2,B,06$ during exit-delay arming.
    The UNO TPI document identifies this class as a keypad one-time sound
    notification.  Field names below are intentionally conservative because
    EyezOn's examples do not expose every possible value.
    """
    parts = data.split(",")
    sound_labels = {
        "B": "beep",
        "C": "chime",
        "E": "error",
        "A": "alarm",
    }
    sound_code = parts[1].strip() if len(parts) > 1 else ""
    return {
        "partition_or_keypad": _safe_int(parts[0]) if len(parts) > 0 else None,
        "sound_code": sound_code,
        "sound": sound_labels.get(sound_code.upper(), "unknown"),
        "parameter": parts[2].strip() if len(parts) > 2 else "",
        "raw_fields": parts,
    }


def decode_keypad_persistent_sound(data: str) -> Dict[str, object]:
    """Decode UNO %0A keypad persistent sound frame.

    Observed example: %0A,2,0,1,1$ during exit-delay arming.
    We log all fields even when the exact semantics are not yet confirmed.
    """
    parts = data.split(",")
    return {
        "partition_or_keypad": _safe_int(parts[0]) if len(parts) > 0 else None,
        "sound_code": parts[1].strip() if len(parts) > 1 else "",
        "state": _safe_int(parts[2]) if len(parts) > 2 else None,
        "pattern_or_priority": _safe_int(parts[3]) if len(parts) > 3 else None,
        "raw_fields": parts,
    }


def decode_partition_chime(data: str) -> Dict[str, object]:
    parts = data.split(",")
    return {
        "partition": _safe_int(parts[0]) if len(parts) > 0 else None,
        "state": _safe_int(parts[1]) if len(parts) > 1 else None,
        "raw_fields": parts,
    }


def _safe_int(value):
    try:
        return int(str(value).strip())
    except Exception:
        return None


def decode_etf(byte_value: int):
    if byte_value == 0:
        return None
    return (byte_value / 2.0) - 40.0


def decode_zone_temperatures(hexstr: str):
    return {i: decode_etf(b) for i, b in enumerate(parse_hex_bytes(hexstr), start=1)}


def decode_partition_temperatures(hexstr: str):
    vals = parse_hex_bytes(hexstr)
    out = {}
    for p in range(1, 9):
        inside = vals[p - 1] if p - 1 < len(vals) else 0
        outside_index = 8 + (p - 1)
        outside = vals[outside_index] if outside_index < len(vals) else 0
        out[p] = {"inside": decode_etf(inside), "outside": decode_etf(outside)}
    return out


def decode_zone_timers(hexstr: str):
    vals = parse_hex_bytes(hexstr)
    out = {}
    for i in range(0, len(vals) - 1, 2):
        zone = (i // 2) + 1
        out[zone] = vals[i] | (vals[i + 1] << 8)
    return out
