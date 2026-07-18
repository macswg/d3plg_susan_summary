# Susan Summary

A Disguise Designer plugin that logs the state of the showfile. Click **Capture
snapshot** and it writes a timestamped JSON file listing every track in the
active setlist, every layer on those tracks (including layers nested in groups),
the media each layer references, and the timings.

The point is a diffable record: run it at the end of each session and
`git diff` two snapshots to see exactly what changed — a renamed layer, a
swapped clip, a retimed cue.

## Install

No build step. Copy this folder to either:

- `<d3 Projects>/common/plugins/susan_summary/` — available to every project on
  the machine, or
- `<project>/plugins/susan_summary/` — that project only.

Then open it from the Plugins menu in Designer.

## Use

| Control | What it does |
| --- | --- |
| **Capture snapshot** | Snapshots the active transport's setlist. |
| **Transport** field | Snapshot a named transport instead of the active one. |
| **Download JSON** | Saves the last snapshot through the browser — useful if the director can't write to disk. |

Snapshots land in `<project>/plugins/susan_summary/logs/`, named
`<timestamp>_<project>.json`. Keys are sorted and indented so consecutive
captures diff cleanly. `logs/` is gitignored here — commit it in the project
repo where the showfile lives, not in this one.

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
covering nested groups, clip swaps, disabled layers, empty tracks, a missing
setlist and an unwritable log dir.

Every snapshot carries a `debug` array recording which access paths worked and
which failed — check it first when a field comes back empty.

## References

- `ref/prewarmAllLayers2sec.py` — the setlist/track/layer traversal this is built on.
- `../d3plg_media_info` — the media field lookups and the director API call pattern.
