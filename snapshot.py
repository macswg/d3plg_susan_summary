# -*- coding: utf-8 -*-
"""Capture the state of the showfile: every track in the active setlist, every
layer on those tracks, the media each layer references, and the timings.

Runs **on the director**. Two ways in:
  - Registered as a module via /api/session/python/registermodule, then invoked
    with `capture()` — how index.js drives it. In that context the director
    injects its globals (guisystem, resourceManager, TransportManager, ...).
  - Imported from the d3 console, the way ref/prewarmAllLayers2sec.py documents:
        sys.path.append("{project}/plugins/susan_summary")
        import snapshot; snapshot.capture()
    In that context the names must come from the `d3` package instead.
`_g()` resolves either way, so the same file serves both.

Output (stdout, single JSON object): the snapshot, plus "writtenTo" naming the
file written under {project}/plugins/susan_summary/logs/. On failure the same
shape carries a non-null "error".

NB: bound-attribute access on the director can raise outside the Exception
hierarchy, so guard director calls with `except BaseException`, never bare
`except Exception` (which would 500 the plugin).
"""
from __future__ import print_function
import json
import time

# NB: `os` is deliberately NOT imported here. When this file is registered as a
# director module, d3 injects its own globals over the module namespace,
# including one named `os` of type `OS` which has no `path`/`makedirs` -- so a
# module-level `import os` silently becomes the wrong object and every write
# fails with "'OS' object has no attribute 'path'". A function-local import
# binds the real module. Use _os() instead of importing at module level.
#
# The director embeds Python 2 (no pathlib, `long`, `os.getcwdu`), so this file
# must stay 2/3 compatible.

__all__ = ["capture", "list_transports"]

SCHEMA_VERSION = 1
MODULE_DIR_NAME = "susan_summary"


def _g(name):
    """Resolve a director name from globals (registered-module context) or from
    the d3 package (console-import context). None if neither has it."""
    if name in globals():
        return globals()[name]
    try:
        import d3
    except BaseException:
        return None
    return getattr(d3, name, None)


def _os():
    """The real `os` module. Must be imported inside a function -- see the note
    at the top of this file."""
    import os
    return os


def _attr(obj, name, default=None):
    """Read a non-callable attribute, or default. Never raises."""
    try:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if not callable(val):
                return val
    except BaseException:
        pass
    return default


def _call(obj, name, default=None):
    """Call a zero-arg method and return its result, or default. Never raises.

    Needed alongside _attr because parts of the director expose data as methods
    rather than properties -- ProjectPathsManager.projectName() / projectFolder()
    are methods, and _attr deliberately skips callables."""
    try:
        method = getattr(obj, name, None)
        if callable(method):
            return method()
    except BaseException:
        pass
    return default


def _name_of(obj):
    """User-facing name. `name` first (it matches the liveUpdate resource path),
    `description` as fallback — same precedence as list_transports.py in
    ../d3plg_media_info."""
    for attr in ("name", "description"):
        val = _attr(obj, attr)
        if val:
            try:
                return str(val)
            except BaseException:
                pass
    return None


def _num(value):
    """Coerce to float for JSON, or None. Never raises."""
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except BaseException:
        return None


# --- resolution -------------------------------------------------------------

def _resolve_transport(transport_name, debug):
    """The named TransportManager, or the active one when unnamed."""
    if not transport_name:
        # The idiom from ref/prewarmAllLayers2sec.py, with the guisystem path
        # used by ../d3plg_media_info as fallback.
        local_state = _g("LocalState")
        if local_state is not None:
            try:
                tm = local_state.localState().currentTransport
                if tm is not None:
                    return tm
            except BaseException as e:
                debug.append("LocalState.currentTransport failed: {0}".format(e))
        guisystem = _g("guisystem")
        try:
            return guisystem.currentTransportManager
        except BaseException as e:
            debug.append("currentTransportManager failed: {0}".format(e))
            return None

    rm = _g("resourceManager")
    tm_type = _g("TransportManager")
    if rm is None or tm_type is None or not hasattr(rm, "allResources"):
        debug.append("cannot enumerate transports")
        return None
    try:
        for tm in rm.allResources(tm_type):
            if _name_of(tm) == transport_name:
                return tm
    except BaseException as e:
        debug.append("allResources(TransportManager) failed: {0}".format(e))
    debug.append("no transport named {0!r}".format(transport_name))
    return None


# --- traversal --------------------------------------------------------------

def _media_records(layer, debug):
    """Every media resource this layer's video sequence references — not just the
    one under the playhead (../d3plg_media_info evaluates at the current time for
    live display; a state log wants them all). Evaluated at the layer's own
    tStart, plus each distinct resource across the sequence's keys, so a layer
    that swaps clips logs all of them."""
    try:
        video_field_seq = layer.findSequence("video")
    except BaseException:
        return []
    if not video_field_seq:
        return []
    sequence = _attr(video_field_seq, "sequence")
    if not sequence:
        return []

    resources = []
    seen = set()

    def _add(resource):
        if not resource:
            return
        key = _attr(resource, "uid") or _name_of(resource)
        if key in seen:
            return
        seen.add(key)
        resources.append(resource)

    # Read the sequence's keys directly. This is the primary source: probe.py
    # found layers whose sequence holds a KeyResource but whose
    # evalResource(tStart) returns None, so relying on eval alone silently drops
    # their media (../d3plg_media_info only ever evals under the playhead, where
    # it works, so it never hit this).
    for key in _attr(sequence, "keys", []) or []:
        # KeyResource holds its media on `r` (confirmed on a real director; its
        # only other members are interpolation/localT/select/tEpsilon). `r` is
        # None when the layer has a video module but no clip assigned -- a
        # normal, empty layer, not a lookup failure.
        for attr in ("r", "resource", "value", "v", "res"):
            candidate = _attr(key, attr)
            if candidate is not None:
                _add(candidate)
                break
        else:
            if _attr(key, "path") is not None or _name_of(key):
                _add(key)

    # Evaluating at the layer's start can surface a clip the keys don't expose
    # directly (e.g. one inherited from before the layer begins).
    try:
        _add(sequence.evalResource(_attr(layer, "tStart", 0.0)))
    except BaseException as e:
        debug.append("evalResource failed: {0}".format(e))

    return [_media_record(r) for r in resources]


def _media_record(media):
    """One media resource, same field set ../d3plg_media_info surfaces."""
    region_set = _attr(media, "regionSet")
    region_set_name = _name_of(region_set) if region_set else None

    path = _attr(media, "path")
    if path is not None:
        path = str(path)
        if path.endswith(".apx"):
            path = path[:-4]

    version = _attr(media, "enabledVersion")

    return {
        "name": _name_of(media),
        "path": path,
        "version": str(version) if version is not None else None,
        "hasAudio": bool(_attr(media, "hasAudio")),
        "regionSet": region_set_name,
    }


def _beat(track, t, debug):
    """Beat position for a track time. Layers carry no beat fields at all
    (confirmed by probe.py on a real director -- bStart/bEnd/startBeat and every
    variant are MISSING), so it has to be derived through the track."""
    if t is None or track is None:
        return None
    # timeToBeat(t) is the one that takes a single argument; globalTimeToBeat
    # needs more and raises "Incorrect number of arguments to call".
    for method in ("timeToBeat", "globalTimeToBeat"):
        try:
            fn = getattr(track, method, None)
            if callable(fn):
                return _num(fn(t))
        except BaseException as error:
            debug.append("{0}({1}) failed: {2}".format(method, t, error))
    return None


def _layer_records(layer, group_path, track, debug):
    """Flatten a layer, recursing into groups. Mirrors getLayerStartTime() in
    ref/prewarmAllLayers2sec.py, except nothing is skipped: that script drops
    layers with renderEnable false, but a disabled layer is still showfile state,
    so it is logged with the flag instead."""
    group_layer = _g("GroupLayer")
    try:
        is_group = group_layer is not None and issubclass(type(layer), group_layer)
    except BaseException:
        is_group = False

    name = _name_of(layer) or "Unknown"

    if is_group:
        records = []
        for sublayer in _attr(layer, "layers", []) or []:
            records.extend(_layer_records(sublayer, group_path + [name], track, debug))
        return records

    try:
        # type(layer) is "Layer" for nearly everything; the module is what
        # actually distinguishes a Video layer from a Notch/Audio/Web one.
        module = _attr(layer, "module")
        return [{
            "name": name,
            "type": type(module).__name__ if module is not None else type(layer).__name__,
            "groupPath": list(group_path),
            "renderEnable": bool(_attr(layer, "renderEnable", True)),
            "tStart": _num(_attr(layer, "tStart")),
            "tEnd": _num(_attr(layer, "tEnd")),
            "bStart": _beat(track, _attr(layer, "tStart"), debug),
            "bEnd": _beat(track, _attr(layer, "tEnd"), debug),
            "media": _media_records(layer, debug),
        }]
    except BaseException as error:
        # Backstop. In practice _attr() absorbs a failing field into None, so the
        # layer above still logs with that one field null; this only fires if
        # something outside those reads blows up. Either way one bad layer never
        # costs us the track.
        return [{"name": name, "groupPath": list(group_path),
                 "error": str(error)[:200]}]


def _track_record(track, debug):
    layers = []
    for layer in _attr(track, "layers", []) or []:
        layers.extend(_layer_records(layer, [], track, debug))
    return {
        "name": _name_of(track),
        "lengthInSec": _num(_attr(track, "lengthInSec")),
        "lengthInBeats": _num(_attr(track, "lengthInBeats")),
        "bpm": _num(_attr(track, "bpm")),
        "layerCount": len(layers),
        "layers": layers,
    }


# --- output -----------------------------------------------------------------

def _project_paths(debug):
    """The ProjectPathsManager, wherever the director hangs it off."""
    for holder_name, attr in (("state", "projectPaths"),
                              ("guisystem", "projectPaths"),
                              ("state", "paths"),
                              ("guisystem", "paths")):
        holder = _g(holder_name)
        if holder is None:
            continue
        paths = _attr(holder, attr) or _call(holder, attr)
        if paths is not None:
            return paths
    debug.append("no ProjectPathsManager found")
    return None


def _project_name(debug):
    """Confirmed on a real director: `state.projectName` is a plain attribute on
    D3State (probe.py, 2026-07-18). The ProjectPathsManager routes are kept as
    fallbacks -- its projectName()/projectFolder() are *methods*, hence _call."""
    state = _g("state")
    name = _attr(state, "projectName")
    if name:
        return str(name)

    paths = _project_paths(debug)
    if paths is not None:
        for method in ("projectName", "projectFileName", "folderName"):
            val = _call(paths, method)
            if val:
                return str(val)
        folder = _call(paths, "projectFolder")
        if folder:
            return _os().path.basename(str(folder).rstrip("/\\"))
    debug.append("project name unresolved")
    return None


def _plugin_dir(debug):
    """This plugin's own folder, {project}/plugins/susan_summary.

    Resolved differently per context, because the director gives no project
    folder attribute:
      - Console import: __file__ is a real path to this file, so use its dir.
      - Registered module: __file__ is the literal string "d3_loader" (not a
        path at all), but the cwd is the project root -- so build the path from
        there. Confirmed on a live director.
    """
    os = _os()
    here = None
    try:
        if __file__ and os.path.isfile(__file__):
            here = os.path.dirname(os.path.abspath(__file__))
    except BaseException:
        here = None
    if here:
        return here

    # Not a real file path: treat the cwd as the project root.
    root = _call(_project_paths(debug), "projectFolder")
    if not root:
        try:
            root = os.getcwd()
        except BaseException:
            root = None
    if root:
        return os.path.join(str(root), "plugins", MODULE_DIR_NAME)

    debug.append("plugin folder unresolved")
    return None


def _log_dir(debug):
    """{project}/plugins/susan_summary/logs -- the logs sit next to the plugin."""
    base = _plugin_dir(debug)
    if base is None:
        return None
    return _os().path.join(base, "logs")


def _write(snapshot, debug):
    """Write the snapshot to disk. Returns the path, or None (the browser still
    gets the JSON and can download it, so a read-only path is not fatal).

    Sets snapshot["writtenTo"] *before* serialising so the file on disk names
    itself; setting it afterwards would leave every saved log claiming null."""
    try:
        directory = _log_dir(debug)
        if directory is None:
            snapshot["writtenTo"] = None
            return None
        if not _os().path.isdir(directory):
            _os().makedirs(directory)
        stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
        project = snapshot.get("project") or "project"
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in project)
        path = _os().path.join(directory, "{0}_{1}.json".format(stamp, safe))
        snapshot["writtenTo"] = path
        handle = open(path, "w")
        try:
            # Sorted keys + indent so consecutive snapshots diff cleanly — the
            # whole point of keeping the log.
            handle.write(json.dumps(snapshot, indent=2, sort_keys=True))
        finally:
            handle.close()
        return path
    except BaseException as error:
        debug.append("write failed: {0}".format(error))
        snapshot["writtenTo"] = None
        return None


def list_transports():
    """Print the available transports so the UI can offer a dropdown instead of
    a free-text field.

    Output: {"transports": [...], "current": "default", "error": null}
    Names come from _name_of, i.e. the same lookup capture() matches against --
    transports have no `name`, so this resolves via `description`.
    """
    debug = []
    names = []
    current = None
    try:
        current = _name_of(_resolve_transport(None, debug))

        rm = _g("resourceManager")
        tm_type = _g("TransportManager")
        if rm is not None and tm_type is not None and hasattr(rm, "allResources"):
            for tm in rm.allResources(tm_type):
                name = _name_of(tm)
                if name and name not in names:
                    names.append(name)
        else:
            debug.append("resourceManager.allResources unavailable")

        # Always offer the active transport, even if enumeration missed it.
        if current and current not in names:
            names.insert(0, current)

        print(json.dumps({"transports": names, "current": current,
                          "error": None, "debug": debug}))
    except BaseException as error:
        print(json.dumps({"transports": names, "current": current,
                          "error": str(error), "debug": debug}))


def capture(transport_name=None):
    """Snapshot the showfile and print it as JSON. Pass a transport name to read
    a specific transport's setlist; omit it for the active transport."""
    debug = []
    snapshot = {
        "schemaVersion": SCHEMA_VERSION,
        "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project": None,
        "transport": None,
        "setlist": None,
        "trackCount": 0,
        "tracks": [],
        "writtenTo": None,
        "error": None,
        "debug": debug,
    }
    try:
        snapshot["project"] = _project_name(debug)

        tm = _resolve_transport(transport_name, debug)
        if tm is None:
            snapshot["error"] = "no transport resolved"
            print(json.dumps(snapshot))
            return snapshot
        snapshot["transport"] = _name_of(tm)

        setlist = _attr(tm, "setList")
        if setlist is None:
            snapshot["error"] = "transport has no setlist"
            print(json.dumps(snapshot))
            return snapshot
        snapshot["setlist"] = _name_of(setlist)

        tracks = _attr(setlist, "tracks", []) or []
        snapshot["tracks"] = [_track_record(t, debug) for t in tracks]
        snapshot["trackCount"] = len(snapshot["tracks"])

        _write(snapshot, debug)  # sets snapshot["writtenTo"] itself
    except BaseException as error:
        snapshot["error"] = str(error)

    print(json.dumps(snapshot))
    return snapshot
