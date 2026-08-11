# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

A Home Assistant custom integration for **ELRO Connects K2** (SF50GA) gateways — smoke, CO,
heat, and water detectors, controlled locally with no vendor cloud. `iot_class: local_push`.

All protocol work lives in the separate **`elro-connects-k2-protocol`** library, imported as a
normal pip requirement (`from elro_connects_k2_protocol.gateway import K2Gateway`). This repo
contains no protocol code and should never gain any — if something needs a new `CMD_CODE`, a
new parse path, or a device-type entry, that change belongs in the library.

## Layout

```
custom_components/elro_connects_k2/
  __init__.py      Setup/unload, debug log level wiring
  coordinator.py   DataUpdateCoordinator wrapping K2Gateway; push callbacks
  config_flow.py   Discovery + manual IP entry
  binary_sensor.py Alarm entities (smoke, CO, gas, heat, moisture) + fault
  sensor.py        Battery, signal, CO2/temp/humidity
  button.py        "Sync now"
  services.py      start_pairing / cancel_pairing actions
  diagnostics.py   Config-entry diagnostics
```

## Key design rule

**Entity creation is driven entirely by `DeviceProfile.capabilities`** from the library — no
hardcoded device-type checks in this repo. Supporting a new detector means adding a profile in
the library, not a branch here. Preserve that when editing `binary_sensor.py` / `sensor.py`.

## Running it

```bash
docker compose up -d          # stock HA image + this integration mounted live
```

Then `http://localhost:8123` → Settings → Integrations → Add → ELRO Connects K2. On macOS,
broadcast discovery does not work through Docker's bridged network; skip discovery and enter
the gateway IP and device name (`ST_xxxxxxxxxx`) manually. On Linux, swap the `ports` block for
`network_mode: host`.

To work on the library at the same time, `cp docker-compose.override.yml.example
docker-compose.override.yml` — that bind-mounts a sibling protocol checkout instead of
pip-installing it. See `ha-deps/README.md` for why the `.dist-info` mount is required.

Develop without hardware using `tools/k2_simulator.py` from the protocol repo: run it on the
host with `device_name = DEMO_DEVICE`, `host = 127.0.0.1`.

## Norms

- Follow Home Assistant integration conventions; `hassfest` and HACS validation run in CI.
- User-visible strings go in `strings.json` + `translations/`, never inline.
- Version coupling: `manifest.json`'s requirement pin, the protocol repo's `pyproject.toml`
  version, and `ha-deps/…dist-info/METADATA` must all match, or HA's requirement check fails.
- Device removal is deliberately unimplemented — it needs `CMD_CODE 4`, which is destructive
  and untested. Don't add it without hardware to verify against.
- The `hacs.json` floor of **2026.3.0** is the release that added local `brand/` images, which
  is where this integration's icon comes from. Below it the integration installs but renders
  with no icon. Don't lower it without moving the icon to the `home-assistant/brands` repo, and
  don't raise it without a concrete API that needs the newer version — CI type-checks against
  whatever `homeassistant` pip resolves to, so the floor is a deliberate claim, not a tested one.
