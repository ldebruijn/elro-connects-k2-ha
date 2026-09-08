# ELRO Connects K2 — Home Assistant integration

Local control of the **ELRO Connects K2** (SF50GA) Wi-Fi gateway for smoke, CO, heat, and
water detectors — no cloud, no vendor app required.

`iot_class: local_push` — HA state updates immediately when the K2 sends a push event, with
no polling delay. This matters for CO and smoke alarms.

Built on [elro-connects-k2-protocol](https://github.com/ldebruijn/elro-connects-k2-protocol),
a standalone async library with no third-party runtime dependencies. That repo also holds the
wire protocol reference and the reverse-engineering notes.

---

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/ldebruijn/elro-connects-k2-ha`, category **Integration**
3. Install **ELRO Connects K2**, restart Home Assistant
4. Settings → Devices & Services → Add integration → **ELRO Connects K2**

### Manual

Copy `custom_components/elro_connects_k2/` into your HA `config/custom_components/` and
restart. HA installs the `elro-connects-k2-protocol` dependency automatically from the
requirement pinned in `manifest.json`.

## Configuration

The config flow discovers K2 gateways by UDP broadcast. If discovery finds nothing — common
when HA runs in a bridged-network container — enter the gateway IP and device name manually.
The device name looks like `ST_1234567890` and is visible in the app (connector > settings > Connector details > device name).

### More than one hub

K2 hubs do not mesh: a house with an outbuilding runs one hub per building, and each hub has
its own detectors. Add them one at a time — run the config flow again and it offers whichever
hubs answered the broadcast and are not set up yet. Every hub gets its own device in Home
Assistant, with its detectors underneath it.

Manual entry works for several hubs too, and mixes freely with discovery — add the hub on
your own subnet from the broadcast, then run the flow again and choose **Enter a gateway
manually** for one on another VLAN. Hand-entered details are checked against the hub before
the entry is created, so a mistyped device name is rejected on the spot rather than producing
an entry that loads and then does nothing.

All the hubs share one UDP socket on port 1025 (the hub only ever talks to that port, so
there is nothing to give a second one), and frames are routed to the right hub by the device
name they carry. Nothing extra to configure.

## Entities created per sub-device

Entity creation is driven entirely by `DeviceProfile.capabilities` — no hardcoded type checks.

| Device example | Entities created |
|---|---|
| Smoke alarm (GS559A, type `013`) | 1 binary_sensor (smoke) + fault + battery sensor + signal sensor |
| CO + Gas alarm (GS891A, type `014`) | 2 binary_sensors (CO, gas) + fault + battery + signal |
| CO2/Temp/Humidity sensor (type `018`) | 3 sensors (CO2 ppm, °C, %) + battery + signal |
| Heat alarm (type `003`) | 1 binary_sensor (heat) + fault + battery + signal |
| Water alarm (type `004`) | 1 binary_sensor (moisture) + fault + battery + signal |

An extra "Sync now" button appears per gateway for on-demand refresh.

## Adding devices

New detectors can be paired straight from HA — the ELRO app is not needed for this.

**Developer tools → Actions → `ELRO Connects K2: Add device`**, then Perform action. The
gateway opens a join window and the action *blocks while it waits* — go trigger the
detector's pairing action (for most detectors, hold the test button; check your model's
manual) before the timeout expires. The response reports what joined:

```yaml
action: elro_connects_k2.start_pairing
data:
  timeout: 60          # optional, 10–300 s, defaults to 60
  # config_entry_id:   # optional; only needed with more than one gateway
```

```yaml
paired: true
sub_id: 7
device_type: "013"
name: Photoelectric Smoke Alarm
model: GS559A variant
already_known: false   # true when the slot was already in use, e.g. a re-pair
```

Entities for the new device appear automatically — the integration re-syncs after a join,
so signal and battery are real values rather than the placeholder the gateway sends with
the join notification.

An `elro_connects_k2_device_paired` event fires on the bus with the same fields plus
`gateway`, so automations can react without owning the action call.
`elro_connects_k2.cancel_pairing` closes the window early.

**There is no device type to choose.** The vendor app's type picker is never transmitted —
it only selects which on-screen instructions to show. The gateway accepts whichever
detector joins during the window, which also means a window left open will adopt the next
detector triggered in range.

Removing a device is not implemented: it needs `CMD_CODE 4`, which is destructive and
untested. Use the ELRO app for that.

## Sub-device nicknames

Custom names set in the ELRO app (e.g. "Hallway") are stored on the K2 hub itself. The
integration fetches them at startup and on every manual sync. When a nickname is present it
appears as a `nickname` attribute on the device's primary alarm entity, alongside
`alarm_state` and `raw_status`.

The hub does **not** push name changes — if you rename a device in the ELRO app while the
integration is running, the new name will only appear after an HA integration reload (or
pressing "Sync now", which re-runs the full sync including names).

---

## Troubleshooting

### No devices appear in Home Assistant

The hub is added, setup reports no error, and no entities show up. The integration raises a
notification in **Settings → Repairs** naming which of two things it is seeing; the card
clears itself as soon as a sync returns a device.

| Notification | What the hub is doing | Where to look |
| --- | --- | --- |
| *…is not responding* | Never acknowledged an activation ping, so it drops every command sent to it | Device name, IP address, UDP port 1025, the hub's own outbound traffic |
| *…reports no devices* | Answering normally, with an empty device list | Pairing, then the hub's own outbound traffic |

In roughly the order worth checking:

- **The device name must match the hub exactly.** The K2 arms its session only for a request
  that names it character for character (`ST_` prefix included). Until it does, it ignores
  commands without a word, which looks identical to an empty hub.
- **UDP port 1025 must be free and reachable in both directions** on the Home Assistant host.
  Nothing else may hold it — not a second copy of this integration, and not the protocol
  library's CLI or probe running on the same machine.
- **Home Assistant needs a direct path to the hub.** In a bridged-network container the hub's
  replies never come back; use host networking.
- **How you firewall the hub matters more than whether you do.** The hub reaches out to
  Alibaba Cloud (`aliyun.com`) on its own account, and while that has nothing to do with local
  control, the *manner* of blocking it does. A rule that fails fast — DNS blackhole, `REJECT`,
  ICMP unreachable — lets the hub give up immediately and carry on. A rule that silently
  **drops** the traffic, which is what country-block rules normally do, leaves the hub
  retransmitting until its own TCP timeout, and while it is stalled like that it stops
  answering local commands. It recovers on its own once that attempt times out, so the
  symptom is intermittent — a sync landing inside the window comes back empty while the next
  one works. One user's missing devices were exactly this. **You do not need to give the hub
  internet access — block it with a reject rule rather than a drop rule.**
- **Check the detectors are actually paired**, in range, and not flat: a sub-device the hub
  has lost contact with is simply left out of the list.

Switch on **debug logging** in the integration options (Settings → Devices & Services → ELRO
Connects K2 → Configure) to see every frame. The line to look for is `Gateway … activated in
<n> ms`, which means the hub is accepting commands; `did not acknowledge any of 3 activation
pings` instead means it is ignoring Home Assistant.

Background on the activation handshake and the call-home stall is in the protocol repo:
[the activation gate](https://github.com/ldebruijn/elro-connects-k2-protocol/blob/main/docs/protocol_reference.md#the-activation-gate)
and [the hub's call home](https://github.com/ldebruijn/elro-connects-k2-protocol/blob/main/docs/research.md#the-hubs-call-home-and-why-how-you-block-it-matters).

---

## Development

### Full local test setup, with no hardware

This is the loop to develop against: a stock Home Assistant container running this
integration, driven by a fake K2 hub. Nothing is mocked — the simulator sends real
XOR-framed UDP packets and the integration parses them exactly as it would from a real hub.

**How the pieces fit.** The simulator runs on your host and sends to `127.0.0.1:1025`.
Compose publishes host UDP 1025 into the container, so those packets reach the gateway
listening inside HA. HA sends its own commands back to `127.0.0.1:1025` — which, inside the
container, is the container itself. The gateway ignores its own messages, so this is
harmless, and it is why the simulator answers on a timer rather than reacting to commands.

**Step 1 — check out the protocol repo next to this one.**

```
your-workspace/
  elro-connects-k2-ha/          ← you are here
  elro-connects-k2-protocol/
```

**Step 2 — enable the library bind-mount.**

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
```

Compose merges `docker-compose.override.yml` automatically. It mounts the protocol library
from your working tree instead of pip-installing it, so library edits take effect on an HA
restart. It also mounts `ha-deps/…dist-info`, which supplies the install metadata HA's
manifest requirement check looks for — see [`ha-deps/README.md`](ha-deps/README.md).

The override is gitignored; the `.example` is committed. Adjust the paths inside it if your
protocol checkout is somewhere other than a sibling directory.

Confirm the merged result before starting — this catches a wrong path immediately:

```bash
docker compose config
```

**Step 3 — start Home Assistant.**

```bash
docker compose up -d
```

First boot takes a minute or two. `ha_config/` is created on the host and holds the database,
users, and config entries; it is gitignored and persists across restarts.

**Step 4 — add the integration.** Open `http://localhost:8123`, create a user if this is a
fresh instance, then **Settings → Devices & Services → Add integration → ELRO Connects K2**.

Broadcast discovery does **not** work here — Docker's bridged network on macOS doesn't carry
it. Skip discovery and enter manually:

```
host        = 127.0.0.1
device_name = DEMO_DEVICE
```

**Step 5 — start the simulator** from the protocol repo, and leave it running:

```bash
cd ../elro-connects-k2-protocol
python tools/k2_simulator.py
```

It presents six devices (smoke, CO+gas, CO2/temp/humidity, water, door/window, radiator
thermostat) and cycles through alarm and sensor push events every few seconds. `--pair` plays
the hub's side of a pairing round; `--once` fires a single sync and exits.

**Step 6 — confirm it works.** Within ~30 s you should see traffic:

```bash
docker compose logs -f --since 2m homeassistant | grep elro_connects_k2_protocol
```

```
Sync response received: 6 device records in this packet source=POLL
Sub-device info received: sub_id=3 co2=650 temp=22.5 humidity=48.0
Push update received: sub_id=5 type=101 alarm=ALARM battery=100% signal=4 bars source=PUSH
```

`source=PUSH` lines are the thing to look for — they prove the local-push path works end to
end. In the UI, 39 entities appear across the six devices.

**On Linux**, replace the `ports` block in `docker-compose.yml` with `network_mode: host`.
Broadcast discovery and real-hardware push events then work without extra configuration.

### Notes on the dev instance

Editing `custom_components/elro_connects_k2/` (or the mounted library) only needs an HA
restart, never a rebuild:

```bash
docker compose restart
```

If you rename a device profile in the library, entity IDs derived from the old name stay
behind in `ha_config/.storage/core.entity_registry` as stale duplicates. Delete them in the UI
(Settings → Entities), or remove and re-add the integration.

To start completely fresh, `docker compose down` and delete `ha_config/`.

### Without the library bind-mount

If you skip the override, HA pip-installs the library from `manifest.json`'s pinned
requirement. That works once the package is on PyPI; until then, install it once after first
start:

```bash
docker compose exec homeassistant \
  pip install --target /config/deps \
  git+https://github.com/ldebruijn/elro-connects-k2-protocol.git@v0.1.2
```

### Lint and type checking

```bash
pip install -r requirements-dev.txt
pip install elro-connects-k2-protocol   # or from git until it is published

ruff check .
mypy custom_components/
```

`mypy` runs in strict mode. Both `homeassistant` **and** the protocol library must be
installed for the run to mean anything — without the library every `SubDevice` field degrades
to `Any` and the strict errors that matter silently stop being reported. Note that an
*editable* install of the protocol library has the same effect, so use a regular install.

CI additionally runs hassfest, HACS validation, JSON parsing, and a check that
`manifest.json`'s version pin matches the `ha-deps` metadata.

### Version bumps

`manifest.json`'s requirement pin, the protocol repo's `pyproject.toml` version, and
`ha-deps/elro_connects_k2_protocol-0.1.2.dist-info/METADATA` must all agree.
