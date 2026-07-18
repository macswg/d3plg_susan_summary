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
import os
import time

__all__ = ["capture"]

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

    # The clip live at the layer's start.
    try:
        _add(sequence.evalResource(_attr(layer, "tStart", 0.0)))
    except BaseException as e:
        debug.append("evalResource failed: {0}".format(e))

    # Anything the sequence keys onto later in the layer.
    for keys_attr in ("keys", "keyframes"):
        keys = _attr(sequence, keys_attr)
        if not keys:
            continue
        for key in keys:
            t = _attr(key, "t", _attr(key, "time"))
            if t is None:
                continue
            try:
                _add(sequence.evalResource(t))
            except BaseException:
                continue
        break

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


def _layer_records(layer, group_path, debug):
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
            records.extend(_layer_records(sublayer, group_path + [name], debug))
        return records

    try:
        return [{
            "name": name,
            "type": type(layer).__name__,
            "groupPath": list(group_path),
            "renderEnable": bool(_attr(layer, "renderEnable", True)),
            "tStart": _num(_attr(layer, "tStart")),
            "tEnd": _num(_attr(layer, "tEnd")),
            "bStart": _num(_attr(layer, "bStart")),
            "bEnd": _num(_attr(layer, "bEnd")),
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
        layers.extend(_layer_records(layer, [], debug))
    return {
        "name": _name_of(track),
        "lengthInSec": _num(_attr(track, "lengthInSec")),
        "lengthInBeats": _num(_attr(track, "lengthInBeats")),
        "bpm": _num(_attr(track, "bpm")),
        "layerCount": len(layers),
        "layers": layers,
    }


# --- output -----------------------------------------------------------------

def _project_name():
    paths = _g("PathsManager")
    for attr in ("projectName", "currentProjectName"):
        val = _attr(paths, attr)
        if val:
            return str(val)
    project_path = _attr(paths, "projectPath") or _attr(paths, "project")
    if project_path:
        return os.path.basename(str(project_path).rstrip("/\\"))
    return None


def _log_dir():
    """{project}/plugins/susan_summary/logs, falling back to this file's own
    directory when the project path can't be resolved."""
    paths = _g("PathsManager")
    project_path = _attr(paths, "projectPath") or _attr(paths, "project")
    if project_path:
        base = os.path.join(str(project_path), "plugins", MODULE_DIR_NAME)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "logs")


def _write(snapshot, debug):
    """Write the snapshot to disk. Returns the path, or None (the browser still
    gets the JSON and can download it, so a read-only path is not fatal)."""
    try:
        directory = _log_dir()
        if not os.path.isdir(directory):
            os.makedirs(directory)
        stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
        project = snapshot.get("project") or "project"
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in project)
        path = os.path.join(directory, "{0}_{1}.json".format(stamp, safe))
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
        return None


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
        snapshot["project"] = _project_name()

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

        snapshot["writtenTo"] = _write(snapshot, debug)
    except BaseException as error:
        snapshot["error"] = str(error)

    print(json.dumps(snapshot))
    return snapshot
