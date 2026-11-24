"""Interactive ED1 HaLow controller; optional USB clock service uses pyserial."""
import argparse
import calendar
import configparser
from pathlib import Path
from datetime import datetime, timedelta, timezone
import cmd
import json
import re
import shlex
import socket
import threading
import time


def swiss_time(utc):
    """Display current Swiss CET/CEST rules without requiring Windows tzdata."""
    try:
        instant = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return "unavailable"
        instant = instant.astimezone(timezone.utc)
        def boundary(month):
            last = calendar.monthrange(instant.year, month)[1]
            day = datetime(instant.year, month, last, 1, tzinfo=timezone.utc)
            return day - timedelta(days=(day.weekday() + 1) % 7)
        offset = 2 if boundary(3) <= instant < boundary(10) else 1
        return instant.astimezone(timezone(timedelta(hours=offset))).isoformat(timespec="milliseconds")
    except (ValueError, TypeError, AttributeError, OverflowError):
        return "unavailable"


CONFIG_KEYS = {
    "config": ("version",),
    "mic1": ("enabled", "mode", "analog_threshold", "analog_lpf", "floor", "absolute_threshold", "relative_threshold", "relative_pulse_min", "absolute_pulse_min"),
    "geophone": ("enabled", "sample_rate_sps", "gain", "filter", "mode", "duty_cycle", "threshold_uv"),
    "geophone_recording": ("sample_rate_sps", "gain", "filter", "mode", "duty_cycle"),
    "recording": ("seconds",),
    "aad": ("standby", "transmission_correction_ms", "contact_window_s", "retry_interval_s"),
    "battery": ("low_warning_mv", "cutoff_mv", "cutoff_delay_s"),
    "halow": ("enabled", "ssid", "password", "country", "bssid"),
    "network": ("mode", "ip", "netmask", "gateway", "dns"),
    "event": ("server_ip", "port"),
    "storage": ("sd_size", "recording_size_per_second"),
    "node": ("nickname",),
}
CONFIG_KEYS["mic2"] = CONFIG_KEYS["mic1"]


def read_config_file(filename):
    """Strict, bounded INI overrides; firmware validates register combinations atomically."""
    data = Path(filename).read_bytes()
    if len(data) > 8192 or b"\0" in data:
        raise ValueError("INI must be at most 8192 bytes, without NUL characters")
    parser = configparser.ConfigParser(interpolation=None, strict=True, delimiters=("=",), empty_lines_in_values=False)
    parser.optionxform = str
    try:
        parser.read_string(data.decode("utf-8-sig"))
    except (configparser.Error, UnicodeError) as error:
        raise ValueError(f"Invalid config.ini: {error}") from error
    if parser.defaults() or not parser.sections():
        raise ValueError("INI requires known sections; DEFAULT is unsupported")
    updates = {}
    for section in parser.sections():
        if section not in CONFIG_KEYS:
            raise ValueError(f"Unknown INI section [{section}]")
        for key, value in parser.items(section):
            if key not in CONFIG_KEYS[section] or len(value) > 79 or any(ord(c) < 32 or ord(c) > 126 for c in value):
                raise ValueError(f"Invalid INI field {section}.{key}")
            updates[f"{section}.{key}"] = value
    if not updates or updates.get("config.version", "1") != "1":
        raise ValueError("Empty or unsupported INI schema (version must be 1)")
    return updates


class Controller(cmd.Cmd):
    """Receive node evidence continuously while commands await correlated replies."""

    prompt = "event> "

    def __init__(self, bind="0.0.0.0", port=5005):
        """Bind the same UDP port configured in the firmware's event section."""
        super().__init__()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind((bind, port))
        self.port = port
        self.sock.settimeout(0.2)
        self.nodes = {}
        self.pending = {}
        self.events = set()
        self.completions = set()
        self.disarms = {}
        self.lock = threading.Lock()
        self.sequence = time.time_ns() // 1000
        self.stopping = threading.Event()
        self.receiver = threading.Thread(target=self.receive, daemon=True)
        self.receiver.start()

    def receive(self):
        """Validate packets, learn hardware identities and acknowledge event metadata."""
        while not self.stopping.is_set():
            try:
                packet, address = self.sock.recvfrom(2048)
                data = json.loads(packet)
                if not isinstance(data, dict) or data.get("protocol") != "ED1":
                    continue
                node, boot = data["node"], data["boot"]
                if not isinstance(node, str) or not isinstance(boot, str):
                    continue
                if not node.startswith("HE-") or any(c.isspace() for c in node + boot):
                    continue
                with self.lock:
                    old = self.nodes.get(node)
                    if old and old[1] == boot and old[0] != address:
                        # Gated wake can obtain a different DHCP lease. Only a
                        # same-boot event or announcement on the existing port may move identity;
                        # unsolicited command replies cannot redirect a pending request.
                        event_id = data.get("event")
                        announcement = data.get("result") in ("READY", "TIME_REQUEST")
                        valid_event = data.get("result") == "EVENT" and isinstance(event_id, int) and 0 < event_id <= 0xFFFFFFFF
                        if address[1] != old[0][1] or not (announcement or valid_event):
                            continue
                    if old and old[1] != boot and data.get("seq") != 0 and data.get("result") != "TIME_REQUEST":
                        continue  # Only a boot announcement may replace the learned generation.
                    # Event packets omit status fields; retain the nickname for this boot.
                    if old and old[1] == boot and "nickname" not in data:
                        data["nickname"] = old[2].get("nickname", "")
                    self.nodes[node] = (address, boot, data)
                    waiter = self.pending.get(data.get("seq"))
                    if waiter and waiter[2] == node and waiter[3] == boot:
                        waiter[1].append(data)
                        waiter[0].set()
                self.service_disarm(node, boot, address, data)
                if data.get("result") == "TIME_REQUEST":
                    nonce = data.get("nonce")
                    if type(nonce) is int and 0 < nonce <= 0xFFFFFFFF:
                        # Capture UTC after parsing/dispatch, immediately before sendto.
                        self.sock.sendto(f"ED1 {node} {boot} 0 TIME {nonce} {time.time_ns() // 1_000_000}".encode(), address)
                elif data.get("result") == "EVENT":
                    event = data.get("event")
                    if not isinstance(event, int) or not 0 < event <= 0xFFFFFFFF:
                        continue
                    self.sock.sendto(f"ED1 {node} {boot} 0 ACK_EVENT {event}".encode(), address)
                    identity = (node, event)
                    if identity not in self.events:
                        self.events.add(identity)
                        print(f"\n{node}: event {event}, SD session {data.get('session')}, "
                              f"recording_ok={data.get('recording_ok')}, "
                              f"recording_error={data.get('recording_error', 'NONE' if data.get('recording_ok') else 'INCOMPLETE')}, "
                              f"trigger={data.get('trigger_source', 'UNKNOWN')}, microphone_mask={data.get('microphone_mask', 0)}, "
                              f"Switzerland={swiss_time(data.get('recording_start_utc'))} "
                              f"[{data.get('timestamp_quality', 'UNAVAILABLE')}], "
                              f"battery={str(data.get('battery_mv', 0)) + ' mV' if data.get('battery_valid') else 'unavailable'}, "
                              f"SD estimate={data.get('remaining_bytes', 0)} bytes / {data.get('remaining_events', 0)} events, "
                              f"completed={data.get('completed_events', 0)}")
                elif data.get("result") == "AAD_WAKE":
                    # Cumulative detections, including USB tests; no recording or EVENT ACK implied.
                    print(f"\n{node}: AAD WAKE DETECTED, microphone_mask={data.get('microphone_mask')}, "
                          f"counts MIC1/MIC2={data.get('counts')} (since boot)")
                elif data.get("result") == "ENTERING_SLEEP":
                    print(f"\n{node}: attempting event sleep ({data.get('radio_mode')}, "
                          f"{data.get('wnm_depth')}); RTT confirms EVENT_SLEEP established.")
                elif data.get("result") == "SLEEP_FAILED":
                    print(f"\n{node}: HaLow sleep failed; AAD disarmed. Check RTT; retry arm or select radio gated.")
                elif data.get("result") == "ARM_EXPIRED":
                    completion = data.get("completion_id")
                    if type(completion) is int and completion > 0:
                        self.sock.sendto(f"ED1 {node} {boot} 0 ACK_COMPLETE {completion}".encode(), address)
                    identity = (node, boot, completion)
                    if identity not in self.completions:
                        self.completions.add(identity)
                        print(f"\n{node}: AAD session completed/disarmed; awake for commands.")
                elif data.get("seq") == 0:
                    if not old or old[:2] != (address, boot):
                        name = data.get("nickname") or node
                        print(f"\n{node}: ready. Run: ping {name}")
                elif not waiter:
                    print(f"\n{node}: late reply: {data.get('result')}")
            except socket.timeout:
                continue
            except (ValueError, KeyError, TypeError, UnicodeError):
                continue
            except OSError:
                if not self.stopping.is_set():
                    print("\nUDP receive failed")
                break

    def request(self, node, operation, *, display=True):
        """Retry the identical sequence/boot tuple; a timeout is never success."""
        with self.lock:
            if node not in self.nodes:
                matches = [identity for identity, (_, _, data) in self.nodes.items()
                           if data.get("nickname") == node]
                if len(matches) != 1:
                    raise ValueError("Nickname missing or ambiguous; run nodes and use a hardware ID.")
                node = matches[0]
            address, boot, _ = self.nodes[node]
            if not boot:
                raise ValueError("Node could not reserve its SD boot identity; inspect SD card.")
            self.sequence += 1
            sequence = self.sequence
            ready, results = threading.Event(), []
            self.pending[sequence] = (ready, results, node, boot)
        payload = f"ED1 {node} {boot} {sequence} {operation}".encode()
        # Saving releases HaLow's shared SD interface and then resumes the radio.
        # Keep the same sequence throughout this longer persistence transaction.
        reply_wait = 10 if operation == "CFG_APPLY" else 2
        try:
            for _ in range(3):
                self.sock.sendto(payload, address)
                if ready.wait(reply_wait):
                    result = results[0]
                    if not display:
                        return result
                    print(json.dumps(result, indent=2))
                    return result
            print(f"{node}: TIMEOUT (command outcome unknown; inspect status before retrying)")
            return None
        finally:
            with self.lock:
                self.pending.pop(sequence, None)

    def do_discover(self, line):
        """discover BROADCAST_IP: rediscover awake nodes after restarting this PC CLI."""
        address = line.strip() or "255.255.255.255"
        socket.inet_aton(address)
        self.sock.sendto(b"ED1 DISCOVER", (address, self.port))

    def do_nodes(self, _):
        """nodes: list discovered hardware names and endpoints."""
        with self.lock:
            for node, (address, boot, data) in self.nodes.items():
                print(data.get("nickname") or "(no nickname)", node, address, boot,
                      "disarm=" + self.disarms.get(node, {}).get("state", "none"))

    def one_node(self, line, operation):
        """Apply a no-argument protocol operation to one exact hardware name."""
        args = shlex.split(line)
        if len(args) != 1:
            raise ValueError("Expected one node nickname or hardware ID (HE-...).")
        return self.request(args[0], operation)

    def do_ping(self, line):
        """ping HE-...: test bidirectional communication."""
        self.one_node(line, "PING")

    def do_status(self, line):
        """status HE-...: retrieve boot evidence and current state."""
        self.one_node(line, "STATUS")

    def config_request(self, node, operation, expected):
        reply = self.request(node, operation, display=False)
        if not reply or reply.get("result") != expected:
            raise ValueError(f"{node}: {reply.get('result') if reply else 'No reply'}; configuration not confirmed")
        return reply

    def config_transaction(self, node, values):
        self.config_request(node, "CFG_BEGIN", "CONFIG_STAGED")
        for key, value in values.items():
            encoded = value.encode("ascii").hex() or "-"
            self.config_request(node, f"CFG_PUT {key} {encoded}", "CONFIG_STAGED")
        self.config_request(node, "CFG_COMMIT", "CONFIG_VOLATILE")
        print(f"{node}: configuration active in RAM; use config {node} apply to save to SD")

    def do_config(self, line):
        """config NODE mic1|mic2|geo|geo_recording show|on|off|KEY VALUE [KEY VALUE ...]
        config NODE recording seconds 10
        config NODE apply             Save RAM settings to SD now.
        config NODE set FILE          Atomically import INI overrides into RAM.
        config NODE show              Show all active settings (password masked).
        Examples: config 6 geo threshold_uv 5000
                  config 6 geo mode duty_cycle duty_cycle 1/16
                  config 6 mic1 analog_threshold 3 analog_lpf 1
                  config 6 mic2 off
        Disarm before changing settings. NODE is always required.
        """
        args = shlex.split(line)
        if len(args) < 2:
            raise ValueError("Usage: config NODE ...; see help config")
        node, target, *values = args
        groups = CONFIG_KEYS
        aliases = {"geo": "geophone", "geo_recording": "geophone_recording"}
        if target == "apply" and not values:
            self.config_request(node, "CFG_APPLY", "CONFIG_SAVED")
            print(f"{node}: RAM settings saved to SD")
            return
        if target == "set" and len(values) == 1:
            self.config_transaction(node, read_config_file(values[0]))
            return
        section = aliases.get(target, target)
        if target == "show" and not values:
            keys = [f"{group}.{key}" for group, names in groups.items() for key in names]
        elif section in groups and values == ["show"]:
            keys = [f"{section}.{key}" for key in groups[section]]
            if section == "geophone": keys += ["geophone.threshold_actual_uv", "geophone.effective_rate_sps"]
        else:
            if section not in groups:
                raise ValueError("Unknown configuration section; see help config")
            if values in (["on"], ["off"]) and section in ("geophone", "mic1", "mic2"):
                values = ["enabled", "true" if values[0] == "on" else "false"]
            if not values or len(values) % 2:
                raise ValueError("Provide KEY VALUE pairs, or show/on/off")
            updates = {}
            for key, value in zip(values[::2], values[1::2]):
                if key not in groups[section] or key in updates:
                    raise ValueError(f"Unknown or repeated key: {key}")
                updates[key] = value
            self.config_transaction(node, {f"{section}.{k}": v for k, v in updates.items()})
            return
        print(f"{node}: active configuration (RAM)")
        for key in keys:
            reply = self.config_request(node, "CFG_GET " + key, "CONFIG_VALUE")
            print(f"{key:<43} {bytes.fromhex(reply['value_hex']).decode('ascii')}")

    def do_arm(self, line):
        """arm NODE [SECONDS]: event sensing indefinitely, or for 1..31536000 seconds."""
        args = shlex.split(line)
        if len(args) not in (1, 2):
            raise ValueError("Usage: arm NODE [SECONDS]")
        operation = "ARM"
        if len(args) == 2:
            seconds = int(args[1])
            if not 1 <= seconds <= 31536000:
                raise ValueError("Arm duration must be 1..31536000 seconds")
            operation += f" {seconds}"
        self.request(args[0], operation)

    def do_disarm(self, line):
        """disarm NODE: retain a request and deliver it at the next node contact."""
        args = shlex.split(line)
        if len(args) != 1:
            raise ValueError("Usage: disarm NODE")
        name = args[0]
        with self.lock:
            matches = [node for node, (_, _, data) in self.nodes.items()
                       if node == name or data.get("nickname") == name]
            if len(matches) != 1:
                raise ValueError("Unknown or ambiguous node; run nodes")
            node = matches[0]
            self.disarms[node] = {"state": "pending", "boot": None, "seq": None, "sent": 0}
        print(f"{node}: disarm requested and pending until next contact")

    def service_disarm(self, node, boot, address, data):
        """Reuse a sequence on retries; renew after boot changes or a BUSY reply."""
        with self.lock:
            request = self.disarms.get(node)
            if not request or request["state"] == "acknowledged":
                return
            if data.get("seq") == request["seq"] and request["boot"] == boot:
                if data.get("result") == "AAD_DISARMED":
                    request["state"] = "acknowledged"
                    print(f"{node}: disarm acknowledged/completed")
                    return
                if data.get("result") in ("BUSY", "STALE_SEQUENCE", "AAD_FAILED"):
                    request["seq"] = None
            now = time.monotonic()
            if request["boot"] != boot or request["seq"] is None:
                self.sequence += 1
                request.update(boot=boot, seq=self.sequence, sent=0)
            if now - request["sent"] < 1:
                return
            payload = f"ED1 {node} {boot} {request['seq']} DISARM".encode()
            self.sock.sendto(payload, address)
            request["sent"] = now
            if request["state"] != "delivered":
                request["state"] = "delivered"
                print(f"{node}: disarm delivered (sent); awaiting acknowledgement")

    def do_radio(self, line):
        """radio NODE wnm|gated [retained|powerdown]: select sleep before arm (default wnm retained)."""
        args = shlex.split(line)
        if len(args) not in (2, 3):
            raise ValueError("Usage: radio NODE wnm|gated [retained|powerdown]")
        node, mode = args[:2]
        depth = args[2] if len(args) == 3 else "retained"
        if mode not in ("wnm", "gated") or depth not in ("retained", "powerdown"):
            raise ValueError("Mode wnm/gated; WNM depth retained/powerdown")
        self.request(node, f"RADIO {mode} {depth}")

    def do_test_record(self, line):
        """test_record HE-...: exercise both mics + seismic -> SD -> timestamped event report."""
        self.one_node(line, "TEST_RECORD")

    def do_quit(self, _):
        """quit: close the PC controller without sending node commands."""
        return True

    do_EOF = do_quit

    def emptyline(self):
        """Do not repeat a recording command when Enter is pressed twice."""

    def onecmd(self, line):
        """Report input/network errors and keep the interactive controller alive."""
        try:
            return super().onecmd(line)
        except (ValueError, OSError) as error:
            print(f"Error: {error}")
            return False

    def close(self):
        """Stop the receiver before releasing the bound socket."""
        self.stopping.set()
        self.receiver.join(timeout=1)
        self.sock.close()


def usb_clock(port, stopping):
    """Supply host UTC while USB is connected; no node clock is inferred from CDC."""
    import serial
    while not stopping.is_set():
        try:
            with serial.Serial(port, 115200, timeout=1, write_timeout=2) as device:
                while not stopping.is_set():
                    device.write(f"time {time.time_ns() // 1_000_000}\n".encode())
                    # Drain CLI replies so long-running host sessions cannot block USB TX.
                    until = time.monotonic() + 15
                    while not stopping.is_set() and time.monotonic() < until:
                        device.read(256)
        except (OSError, serial.SerialException) as error:
            print(f"USB clock ({port}): {error}; retrying in 5 s")
            stopping.wait(5)


def main():
    """Run on the PC connected to HaLowLink2; permit UDP on the selected port."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--usb", help="Node CDC port (e.g. COM7); supply host UTC every 15 s; requires pyserial")
    parser.add_argument("--command", action="append", help="Run a command after discovery, then exit; repeat for a script")
    parser.add_argument("--discovery-timeout", type=float, default=30, help="Seconds to wait for discovery in command mode")
    args = parser.parse_args()
    if args.usb:
        try:
            import serial  # noqa: F401
        except ImportError:
            parser.error("--usb requires: python -m pip install pyserial")
    controller = Controller(args.bind, args.port)
    clock_thread = None
    if args.usb:
        clock_thread = threading.Thread(target=usb_clock, args=(args.usb, controller.stopping), daemon=True)
        clock_thread.start()
    try:
        if args.command:
            deadline = time.monotonic() + args.discovery_timeout
            while not controller.nodes and time.monotonic() < deadline:
                controller.stopping.wait(0.1)
            for command in args.command:
                name, _, line = command.partition(" ")
                method = getattr(controller, "do_" + name, None)
                if method is None:
                    raise ValueError(f"Unknown command: {name}")
                method(line)
        else:
            controller.cmdloop("Waiting for nodes. Type help for commands.")
    except KeyboardInterrupt:
        pass
    finally:
        controller.close()
        if clock_thread:
            clock_thread.join(timeout=3)


if __name__ == "__main__":
    main()
