# Susan Summary

A Disguise Designer plugin that logs the state of the showfile. Click **Capture
snapshot** and it writes a timestamped JSON file listing every track in the
active setlist, every layer on those tracks (including layers nested in groups),
the media each layer references, and the timings.

The point is a diffable record: run it at the end of each session and
`git diff` two snapshots to see exactly what changed — a renamed layer, a
swapped clip, a retimed cue.

Each snapshot also records the software underneath: the Designer build it was
captured on, and the advanced project settings (the toggles disguise calls
*option switches*, e.g. `useLegacySLCRegionTag`). Those change how a showfile
behaves without changing anything else in the capture, so without them a pair of
snapshots spanning an upgrade — or taken off two different servers — looks
identical when it is not.

## Install

No build step, no dependencies. Download `susan_summary.zip` from the
[latest release](https://github.com/macswg/d3plg_susan_summary/releases/latest)
and unzip it — or just clone this repo — then put the `susan_summary/` folder in
either:

- `<d3 Projects>/common/plugins/susan_summary/` — available to every project on
  the machine, or
- `<project>/plugins/susan_summary/` — that project only.

Then open it from the Plugins menu in Designer.

## Use

| Control | What it does |
| --- | --- |
| **Capture Snapshot to logs** | Writes a snapshot of the setlists in scope to `logs/` on the director. |
| **Transport** dropdown | Scope of the capture: **all transports** (default), the active one only, or a named one. ↻ re-queries the list. |

There is deliberately no browser-side download. Designer's plugin launcher
embeds plugins in an iframe with
`sandbox="allow-same-origin allow-scripts allow-popups allow-forms"` — no
`allow-downloads` — so downloads, the file picker and the clipboard are all
blocked there. The director writes the file instead, which works regardless.

Where a track carries timecode tags, times are shown and logged as timecode
(`01:00:02.27`) instead of seconds; tracks without them keep seconds. Each track
also records its cues — section breaks, notes and TC/CUE/MIDI tags.

Every layer carries an `id` that is stable between captures, plus the `uid` it
came from and an `idSource` saying whether the id is the layer's own UID or was
derived from its name and extents. Layer names are not unique — 814 of the 1935
layers in the test project share a group path and name with a sibling, and 10 of
those match on timing too — so without an id a diff cannot tell which of two
identical layers was removed.

Each track also carries its resource `path` (`objects/track/140_one_one.apx`)
and a `trashed` flag, and its `id` is derived from that path rather than from
the order the setlists happen to be walked — so two tracks sharing a display
name keep the same ids from one capture to the next, and a diff doesn't report a
track removed and re-added when nothing changed.

Alongside the loaded setlists, every snapshot records a `showfile` census — the
track ids in `objects/setlist/automatic.apx`, which loads whatever any transport
has active — so a diff can tell a track *deleted from the showfile* from one
merely *dropped from a setlist*. It holds ids only, never track bodies; if the
census can't be read, `trackIds` is `null` (not `[]`) and `error` says why,
while the rest of the capture proceeds.

Snapshots land in `<project>/plugins/susan_summary/logs/` (next to the plugin), named
`<date>_<time>_<project>.json`. Keys are sorted and indented so consecutive
captures diff cleanly. `logs/` is gitignored here — commit it in the project
repo where the showfile lives, not in this one.

## Building

`sh tools/build.sh` stages the files Designer loads into `build/susan_summary/`
and zips them to `build/susan_summary.zip` — the same layout the install
instructions above describe, so the zip unzips straight into a `plugins/`
folder. It runs the test suite first and refuses to package a failing tree.
Tests, tools, `ref/` and `CLAUDE.md` are development material and stay out of
the zip. `build/` is gitignored.

This is packaging, not compiling. There is still no build step in the sense that
matters: the files that ship are the files in the repo, byte for byte.

## How it works

`index.js` registers `snapshot.py` with the director once per page load, then
calls it:

```
POST /api/session/python/registermodule  {moduleName, contents}
POST /api/session/python/execute         {moduleName, script: "capture()"}
```

`snapshot.py` does the traversal on the director — `currentTransport` →
`setList.tracks` → `track.layers`, recursing into `GroupLayer` — and writes the
file, since the browser has no filesystem access. It prints the snapshot as JSON
on stdout, which comes back in the response's `pythonLog`.

## Debugging

`snapshot.py` runs standalone from the d3 console, which is faster to iterate on
than the plugin UI:

```python
import sys
sys.path.append(r"C:\path\to\d3 Projects\common\plugins\susan_summary")
import snapshot
snapshot.capture()
```

`tests/test_snapshot.py` exercises the whole traversal against fake director
objects (no Designer, no dependencies — just `python tests/test_snapshot.py`),
covering nested groups, clip swaps, disabled layers, empty tracks, path-derived
track ids (including trashed tracks and an unreadable path), the showfile
census, a missing setlist and an unwritable log dir.

`tools/ui_test.js` drives the real plugin page in Chrome — clicks Capture,
reports what rendered, screenshots it, and fails on any page error. It needs
Designer running and `npm i puppeteer-core` (which drives your installed Chrome
rather than downloading one):

```
node tools/ui_test.js            # all transports
node tools/ui_test.js @active
node tools/ui_test.js <name>
```

Every snapshot carries a `debug` array recording which access paths worked and
which failed — check it first when a field comes back empty.

## References

- `ref/prewarmAllLayers2sec.py` — the setlist/track/layer traversal this is built on.
- `../d3plg_media_info` — the media field lookups and the director API call pattern.
