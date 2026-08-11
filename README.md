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
  git+https://github.com/ldebruijn/elro-connects-k2-protocol.git@v0.1.0
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
`ha-deps/elro_connects_k2_protocol-0.1.0.dist-info/METADATA` must all agree.
