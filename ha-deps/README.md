# `ha-deps` — fake install metadata for local library development

This directory is only used by `docker-compose.override.yml.example`, the opt-in
setup for developing this integration and the protocol library at the same time.
The default `docker-compose.yml` does not touch it — there, HA pip-installs the
library normally and a real install brings its own metadata.

The override makes the protocol library importable inside the stock Home
Assistant image by putting `/workspace` on `PYTHONPATH` and bind-mounting
`elro_connects_k2_protocol/` there from a sibling checkout. That alone is enough
for `import elro_connects_k2_protocol` to work.

It is *not* enough for the integration's `manifest.json`, which declares a real
requirement:

```json
"requirements": ["elro-connects-k2-protocol==0.1.0"]
```

At setup HA calls `homeassistant.util.package.is_installed()`, which resolves
the version through `importlib.metadata`. A bare package directory has no
distribution metadata, so the check fails and HA tries to `pip install` the
package — and setup aborts if it can't.

The `.dist-info` directory here supplies that metadata. `importlib.metadata`
discovers distributions by scanning `sys.path` entries, so mounting it next to
the package under `/workspace` makes the requirement resolve as satisfied and
HA skips installation entirely.

**Keep `Version:` in `METADATA` in sync with `[project] version` in the protocol
repo's `pyproject.toml` and with the pin in `manifest.json`.** All three must
match or the requirement check fails.

Delete this directory once the library is published to PyPI and you no longer
need live-editing of library source.
