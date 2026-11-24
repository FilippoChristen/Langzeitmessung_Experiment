# Configuration reference

These files use the same schema as `/heimdall/config.ini` on the SD card.
SD configuration loads at boot. From `tools/event_node.py`, disarm first, then
`config NODE set experiments/mics_only.ini` to apply overrides in RAM and
`config NODE apply` to save them. Omitted import fields keep current RAM values;
omitted SD fields use compiled defaults. Use decimal numbers, `true`/`false`,
and whole-line comments (no trailing comments). Maximum file size: 8192 bytes.

**Check the contents, not the filename:** the current `mics_only.ini` also enables
geophone triggering. Set `[geophone] enabled=false` for microphones only.
Detector enable flags select triggers; a recording still acquires both microphones
and the geophone. Recording duration and the optional `arm NODE SECONDS` monitoring
period are independent. There is no pre-trigger recording.

## General, power and communications

| Section / parameter | Meaning |
|---|---|
| `config.version` | Schema version; must be `1`. |
| `node.nickname` | Optional unique CLI alias (up to 15 letters, digits, `_`, `-`). Hardware identity remains unchanged. |
| `battery.low_warning_mv` | Battery voltage below which event reports flag low battery; 3100?3800 mV, at least `cutoff_mv`. |
| `battery.cutoff_mv` | Stored cutoff setting, 3100?3500 mV. Currently not consumed by the runtime power driver; changing it does not configure shutdown. |
| `battery.cutoff_delay_s` | Stored cutoff delay, 1?60 s. Currently not consumed by the runtime power driver. |
| `halow.enabled` | Enable HaLow networking. False permits USB-controlled measurements without radio reporting. |
| `halow.ssid` | Access point network name, 1?32 characters. |
| `halow.password` | Network password, 8?63 characters; stored as plain text on SD. |
| `halow.country` | Regulatory region code accepted by firmware (e.g. `EU`). |
| `halow.bssid` | Lock to an AP MAC address, or `auto` to allow any matching AP. |
| `network.mode` | `dhcp` for assigned addressing, `static` for the values below. |
| `network.ip` | Node IPv4 address; fallback address when using DHCP. |
| `network.netmask` | IPv4 subnet mask. |
| `network.gateway` | IPv4 router address. |
| `network.dns` | IPv4 DNS server address. |
| `event.server_ip` | PC IPv4 address reachable from the node through HaLow; receives reports and supplies time. |
| `event.port` | UDP port, 1?65535; match the controller's `--port` (default 5005). |
| `storage.sd_size` | Total usable event capacity in bytes, **not free space**; `0` derives capacity from FAT geometry. |
| `storage.recording_size_per_second` | Estimated combined storage per recording second, 1?1000000 bytes/s. Used for remaining-space/event estimates, not recording bitrate. Calibrate using actual files. |
| `recording.seconds` | Length of each event/manual test recording, 1?3600 s. Startup self-test remains one second. |

Network changes take effect through network initialization/reconnection paths;
changing the peer address can interrupt a configuration exchange.

## Event-Trigger timing (`[aad]`)

The existing INI section name `[aad]` is retained for compatibility. These settings
apply to event monitoring, including geophone triggers.

| Parameter | Meaning |
|---|---|
| `standby` | Permit MCU Software Standby during event listening. Enabled microphone detectors must use analog mode; use false for digital modes. Geophone-only listening is supported. Radio sleep policy is selected separately with `radio NODE ...`. |
| `contact_window_s` | Awake communication grace period, 5?120 s: after a recording or periodic radio wake, allow time to reconnect, exchange time, deliver queued event reports and receive commands such as deferred disarm before returning to listening sleep. Also bounds waiting for a recording report ACK before rearming. It is not recording duration or a guarantee of that many seconds of usable network connection; reconnect/processing consumes time and other state conditions can delay sleep. |
| `retry_interval_s` | Periodic contact wake delay, 60?86400 s, measured from successful radio sleep entry. Opens another contact window even without a sensor trigger, allowing queued reports and deferred commands to be serviced. Sensor triggers can wake earlier. |
| `transmission_correction_ms` | Assumed communication delay correction, 0?10000 ms. Added to received PC UTC when setting the RTC offset; subtracted when reconstructing recording start from a post-recording PC reply. Leave 0 unless calibrated; it cannot remove variable latency or RTC drift. |

Unacknowledged recording reports remain in the SD outbox across contact windows.
A sleeping radio cannot immediately receive PC commands.

## Geophone

`[geophone]` configures listening; `[geophone_recording]` independently configures
startup-test and event acquisition. The five shared parameters below apply to both.

| Parameter | Meaning |
|---|---|
| `enabled` (listening only) | Enable geophone threshold triggers when armed; does not disable geophone recording. |
| `sample_rate_sps` | Requested continuous ADC output rate in samples/s (up to three decimal places). Rounded to a supported filter divisor. Duty-cycle mode has additional settling latency, so actual listening rate is lower. |
| `gain` | ADC programmable gain: 1, 2, 4, 8, 16, 32, 64 or 128. Higher gain improves small-signal resolution but reduces input range. |
| `filter` | ADC filter: `sinc3`, `sinc3_rej60`, `sinc4`, `sinc3_sinc1`, `sinc4_sinc1`, or `post1`?`post4`. Controls noise rejection, supported rates and settling time. |
| `mode` | `continuous` for continuous conversion or `duty_cycle` for low-power intermittent conversion. |
| `duty_cycle` | `off` with continuous mode; `1/4` or `1/16` with duty-cycle mode. These select ADC duty operation, not recording duration. |
| `threshold_uv` (listening only) | Symmetric electrical input threshold in microvolts: either polarity can trigger. Quantized outward to ADC comparator steps (~1220.703/gain ?V); must fit the gain-dependent input range. Not a calibrated ground-motion threshold. |

See [supported filter/rate combinations](../docs/configuration.md) and
[threshold quantization](../docs/geophone-configuration.md). `config NODE geo show`
reports actual threshold and effective rate. Maximum ADC rate does not guarantee
lossless SD recording at that rate.

## Microphones (`[mic1]`, `[mic2]`)

Both sections have the same fields; these configure the T5838 acoustic detector,
not the stereo PCM recording format. AAD remains the correct hardware term here.

| Parameter | Meaning |
|---|---|
| `enabled` | Allow this microphone to trigger a recording. |
| `mode` | `analog`, `digital1`, or `digital2` detector. Digital1 needs a running clock and cannot share it with another enabled analog/digital2 detector. |
| `analog_threshold` | Analog sound threshold code 0?15: nominal `60 + 2.5 ? code` dB SPL (4 = 70 dB, 12 = 90 dB). Higher values need louder sound. |
| `analog_lpf` | Analog low-pass cutoff code 1?7: respectively 4.4, 2.0, 1.9, 1.8, 1.6, 1.3, 1.1 kHz. |
| `floor` | Digital relative detector minimum signal-floor code, 15?1980. Raw T5838 code, not dB or ?V. |
| `absolute_threshold` | Digital absolute signal threshold code, 15?1980. Raw T5838 code. |
| `relative_threshold` | Digital signal-change threshold relative to the tracked floor, code 36?255. Raw T5838 code. |
| `relative_pulse_min` | Digital relative detector minimum pulse-duration code, 0?300. Code 0 is approximately 0.7 ms, not zero duration. |
| `absolute_pulse_min` | Digital absolute detector minimum pulse-duration code, 0?3500. Code 0 is approximately 1.1 ms, not zero duration. |

Analog fields affect analog mode; digital fields affect digital modes. Pulse codes
are not milliseconds. See [T5838 details](../docs/T5838_AAD.md) for register references.

## Long measurements and logs

Run `python tools/event_node.py --log measurements.log`. Keep the controller
running and the PC awake/reachable. Reuse the same filename after a controller
restart to resume the history. Use a new file after replacing/reformatting a node's
SD card because event IDs are allocated persistently on that card.

At the `event>` prompt:

- `summary` shows per-node unique recording counts, successes/failures and error counts, total
  reported recording duration, trigger and timestamp-quality counts, and first/last
  PC receipt times for the selected log. Also printed on normal exit and appended to the log.
- `export measurements.csv` writes one row per recording with sensor attribution,
  recording UTC, timestamp quality, errors, battery and storage estimates.

The plain-text log opens in any text editor. Each recording starts with a readable
one-line summary (node, event number, success/failure, trigger, duration and time),
followed by indented report details. Lifecycle/status replies (including sleep
failures, completion, arm/disarm and wake notices) are also logged and may repeat.
Configuration-value replies are excluded. Logging starts when the CLI starts,
not when the module is imported. Events are flushed to disk before ACK; retransmissions
are ACKed again but do not duplicate recording totals, even after a controller restart.
A log write failure is printed and the report remains unacknowledged for retry.

Totals describe **received reports**, including manual test recordings and failures,
not every physical threshold crossing. Detection is interrupted by recording and
rearming; wake notices are not recordings. PC receipt time can be much later than
recording time. Preserve timestamp quality (`AP_SYNCHRONIZED`, `IMPRECISE`,
`UNAVAILABLE`) when analyzing time. Radio wake notices are best effort; pending SD
reports require a later successful contact. Back up the log after closing the
controller; CSV can be regenerated from it. To inspect an existing log without a
node, start the CLI with that `--log` path and use `summary`/`export`.

General firmware replies use `EVENT_TRIGGER_ARMED`, `EVENT_TRIGGER_DISARMED`,
`EVENT_TRIGGER_FAILED`, and `EVENT_TRIGGER_WAKE`; status uses `event_trigger`.
The controller also accepts legacy `AAD_*` replies. Microphone-specific AAD
configuration commands and the `[aad]` INI section keep their existing names.
