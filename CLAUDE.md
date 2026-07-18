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
- **Some director data is exposed as methods, not properties.**
  `ProjectPathsManager.projectFolder()` / `.projectName()` are methods, and
  `_attr()` deliberately skips callables — use `_call()` for those. This cost a
  live run: `project` came back null on the first real capture.
- `type(layer).__name__` is `"Layer"` for nearly everything. The *module* type
  (`type(layer.module).__name__`) is what distinguishes Video / Notch / Audio /
  Web layers.
- Anything written into the snapshot dict must be set **before** `_write`
  serialises it. `writtenTo` was set afterwards at first, so every saved log
  claimed `"writtenTo": null` while sitting at that exact path.

## Confirmed against a real director (2026-07-18)

Working: setlist resolution (`automatic` set list), track names/bpm/lengths,
layer names, `tStart`/`tEnd`, `renderEnable`, media name/path/version,
`.apx` stripping, the log file write.

Unconfirmed: `bStart`/`bEnd` came back null — the beat-field names are still
wrong. `regionSet` was null throughout, which may be correct or may be the wrong
attribute. Run `tools/probe.py` on the director to settle both; it dumps every
public member of a real track, layer, module, sequence and media resource.

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
