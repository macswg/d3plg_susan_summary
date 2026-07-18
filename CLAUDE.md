# CLAUDE.md

Disguise Designer plugin that snapshots showfile state to a diffable JSON log.
See README.md for install and usage.

## Shape

Deliberately a **minimal internal plugin**: no build step, no npm, no relay
server. Plain `index.html` + `index.js` + `snapshot.py`, copied straight into a
`plugins/` folder. Keep it that way — if a change seems to need a bundler,
reconsider it first.

- `snapshot.py` — runs **on the director**, does all the traversal, writes the
  log file. All the real logic lives here.
- `index.js` — registers the module, calls `capture()`, renders the result.
- `d3plugin.json` — manifest; the `name` is what Designer shows.

## Two execution contexts

`snapshot.py` must work both as a registered module (director injects
`guisystem`, `resourceManager`, `TransportManager`, ... as globals) and as a
console import (those names must come from the `d3` package). `_g(name)`
resolves either way — use it instead of referencing those names directly.

## Director gotchas

- Guard director attribute access with `except BaseException`, never bare
  `except Exception`. Bound-attribute access can raise outside the `Exception`
  hierarchy and would 500 the plugin. `_attr()` already does this.
- `registermodule` takes the code under `contents`, not `script`. Only `execute`
  takes `script`.
- Python "returns" data by printing JSON to stdout; it arrives in the response's
  `pythonLog`.
- Media `path` has an `.apx` suffix that must be stripped.

## Design decisions worth keeping

- **Every layer is logged**, including `renderEnable == false` ones (flagged, not
  skipped) and layers outside the playhead. `ref/prewarmAllLayers2sec.py` skips
  disabled layers and `../d3plg_media_info` filters to the playhead — both are
  right for their purposes, wrong for a state log.
- **All media per layer**, not just the clip under the playhead, so a layer that
  swaps clips logs all of them.
- **Sorted keys, indented output.** The log's value is that consecutive
  snapshots diff cleanly. Don't switch to compact JSON.
- **Failures degrade, never abort.** An unreadable field becomes `null` (via
  `_attr`) and the layer is still logged with everything else that read cleanly;
  `null` is distinguishable from a real `0.0`. The per-layer `except` is a
  backstop below that, and every failed access path is appended to `debug`.

## References

- `ref/prewarmAllLayers2sec.py` — authority for the setlist → tracks → recursive
  layer traversal idioms.
- `../d3plg_media_info` — media field lookups (`src/get_video_asset.py`),
  transport lookup (`src/list_transports.py`), director API call pattern
  (`server/director-poller.js`).
- `d3-expert` MCP for the Python API reference.
