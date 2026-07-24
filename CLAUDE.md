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

## Timecode

Use **`track.beatToGlobalTime(beat, clockType, False)`** — it is per track.
Do **not** use `TransportManager.beatToTimecode()`: it is transport-level and
reports the *active* track's timecode for every track, which was measured
giving a track with no tags a confident, wrong `01:00:13`. It is used here only
to read the frame rate (`.fps()`), since the clock type isn't exposed directly.

A track has timecode **iff it carries a TC tag** (`tagAtBeat(beat, 0)`). Without
one, `beatToGlobalTime` echoes the track time straight back — so `hasTimecode`
gates every `tcStart`/`tcEnd`/`cues[].timecode`, and they are null otherwise.

Positions **before the first TC tag** also get null, and fall back to track time
in the UI. Designer reports `00:00:00.00` there, which reads as a real position
rather than "no timecode yet". `firstTimecodeBeat` on the track records where it
starts. Never show a timecode that doesn't exist.

Tag types: `0` = TC, `1` = CUE, `2` = MIDI. Frame rates map to clock types
`{23.976: 0, 24: 1, 25: 2, 29.97: 3, 29.97DF: 4, 30: 5}`.

Cues come from `track.cueBeats()` + `track.cueAtBeat(beat)`; the `Cue` carries
`note` and `section`. Cues with no section, note or tag are dropped — a bare cue
is timeline noise, not showfile state.

## Timestamps are local

`capturedAt` is local time with a UTC offset (`2026-07-18T19:43:51-07:00`), and
the filename stamp is derived from it rather than a second clock read, so the
two can never disagree. It was UTC, which filed an evening show under the next
day's date — operators name sessions by the day they worked. The offset keeps it
unambiguous when logs move between machines. Note this makes `capturedAt` sort
lexicographically only within one timezone.

## Schema

`schemaVersion` is **5**. Tracks are stored **once** in a top-level `tracks`
array, each with an `id`; transports carry `trackRefs` pointing into it. Setlists
share tracks, so writing them inline duplicated the payload — one layer edit
produced an identical diff hunk per transport, and the file was twice the size
(37KB → 19KB on the test project). The app still renders tracks grouped per
transport by resolving the refs.

### Track identity is the resource path (v5)

Identity is `track.path` (`objects/track/140_one_one.apx`) — the file identity,
which cannot collide. `uid` then the name are ordered fallbacks when the path
can't be read; a capture must never fail over this. Each track record carries
`path` (so the id is auditable) and `trashed` (path under `trash/`).

The **id is a pure function of the track**: `_track_id(name, path)` looks at
nothing already in the registry. Plain name for `objects/track/<name>.apx`,
`<name> #trash` for a trashed resource, `<name> #<file stem>` when the file name
says something the display name doesn't. Until v5 the id was the display name
plus a ` #<n>` counter minted in *encounter order*, so changing which setlist a
transport had loaded could move the suffix to the other resource — and the
viewer, which matches by `id`, then reported a whole 37-layer track removed and
another added for a showfile where nothing had changed.

Two same-named tracks are usually not a bug: the live session that prompted this
had `objects/track/140_one_one.apx` and `trash/objects/track/140_one_one.apx` —
genuinely different resources, one trashed and still referenced by a setlist.
The uid keying was working; the id scheme was what was broken.

**Diffing a v5 capture against a v4 one on disk**: ids move for tracks whose
file stem differs from the display name and for anything under `trash/`, so
those read as one removed + one added. One-time cost at the version boundary.

### `showfile` census (v5)

`tracks` is only the union of what the *loaded* setlists reference, so a track
dropped from a setlist vanishes and a diff can't tell "deleted from the
showfile" from "dropped from a setlist". `showfile` loads
`objects/setlist/automatic.apx` through `resourceManager.load()` — which works
regardless of what any transport has active — and records membership:

```json
"showfile": {"source": "objects/setlist/automatic.apx",
             "trackIds": [...], "trackCount": 126, "error": null}
```

**Ids only, never bodies.** Bodies would add ~750KB per capture and force a
`track.layers` traversal of all 126 tracks, which is the documented
Designer-crash exposure. Ids resolve the same way a `trackRef` does
(`registry.id_for`, which mints the id without capturing the body), so the
viewer can match them against `tracks[].id`. The census never adds a track to
`tracks` — bodies still come from the loaded setlists. On failure `trackIds` is
**`null`, never `[]`**: the viewer must tell "no census" from "empty showfile".
`error` carries the message, `debug` gets a line, and the capture proceeds.

**Don't read the display name you don't need.** `id_for` keys on `_track_path`
alone and returns a registry hit before touching the name; `_key_of` is the one
place the path → uid → name fallback chain lives (so `add` and `id_for` cannot
key a track differently), and `_mint_id` is the only thing that reads the name.
On a live session (2026-07-24) sweeping `.path` across every setlist took ~25ms,
while one call reading `.description` for all 126 automatic-setlist tracks
preceded a Designer freeze. Correlation, not proof — but this runs on a timer in
a session that may be in a show, so the cheap path stays cheap. There is a test
that fails if a registry hit reads `.description` again.

v4 deduplicated the tracks. v3 added `cues` (section breaks, notes, tags),
`hasTimecode`/`fps` and `tcStart`/`tcEnd`. A snapshot holds a `transports` array — `capture()`
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
