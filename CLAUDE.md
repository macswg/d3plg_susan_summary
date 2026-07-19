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

## The sandbox is Python 2, and `os` is booby-trapped

The director embeds **Python 2** (no `pathlib`, `long`, `os.getcwdu`), so this
file must stay 2/3 compatible.

When registered as a module, d3 injects its globals over the module namespace —
including one named `os` of type `OS` with no `path`/`makedirs`. A module-level
`import os` therefore silently becomes the wrong object and every write dies with
`'OS' object has no attribute 'path'`. A *function-local* import gets the real
module; that's what `_os()` is for. **Never add a module-level `import os`.**

This only bites in the registered-module path — the console path has real `os`,
so the bug is invisible when testing via `import snapshot`.

## Confirmed against a real director (2026-07-18)

Working end-to-end through the sandbox: project name, setlist, tracks, layers,
module types, `tStart`/`tEnd`, derived beats, media name/path/version/regionSet,
`.apx` stripping, and the log file write (self-naming verified).

- `KeyResource.r` holds the media. Its only other members are
  `interpolation`/`localT`/`select`/`tEpsilon`/`cubic`/`linear`/`null`. `r` is
  `None` when a layer has a video module but no clip assigned — an empty layer,
  **not** a lookup failure. Don't "fix" that into a warning again.
- `track.timeToBeat(t)` takes one argument; `globalTimeToBeat` /
  `beatToGlobalTime` need more and raise "Incorrect number of arguments".
- `state.projectName` works; there is no project *folder* attribute. In the
  registered-module context `__file__` is the literal string `"d3_loader"` (not
  a path), but the cwd is the project root — so `_plugin_dir()` builds
  `{cwd}/plugins/susan_summary` there, and uses `__file__`'s directory when it
  is a real path (console import). `writtenTo` always records where it landed.
- Layer `name` is set but transport/setlist `name` is not — `_name_of` falls
  back to `description`, which is why those resolve.

Re-run `tools/probe.py` when a field comes back empty; it dumps every public
member of a real track, layer, module, sequence, key and media resource.

## Schema

`schemaVersion` is **2**. A snapshot holds a `transports` array — `capture()`
defaults to *every* transport, since a state log should cover the whole showfile
unless deliberately narrowed. Version 1 had a single top-level
`transport`/`setlist`/`tracks`; the four v1 logs in the test project are not
comparable with v2 ones. Bump the version on any further shape change.

Scopes: `capture()` = all, `capture(active_only=True)` = active,
`capture("name")` = that one. `index.js` maps the dropdown to these, using
`@active` as the sentinel for the active-only option.

A transport that fails (e.g. no setlist) records its error in its own entry
rather than aborting the capture — one bad transport must not cost the others.

## No browser-side export — don't re-add it

Designer's plugin launcher (`http://localhost/`) embeds plugins in an iframe
with `sandbox="allow-same-origin allow-scripts allow-popups allow-forms"`.
Inside it, measured directly:

- `showSaveFilePicker` → `SecurityError: Cross origin sub frames aren't allowed
  to show a file picker`
- anchor download → silently blocked, `allow-downloads` is absent
- `navigator.clipboard.writeText` → rejected

Popups don't escape it either (no `allow-popups-to-escape-sandbox`). A Download
button, a Save As dialog and a director-side "save copy to path" were all built
and then removed — the director already writes the log to `logs/`, which is the
deliverable. If someone asks for a download again, the answer is to open the
plugin URL directly in a browser, not to add a button that cannot work.

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
