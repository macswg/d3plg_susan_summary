# -*- coding: utf-8 -*-
"""Dump what the real director objects actually expose, so snapshot.py can be
corrected against fact rather than guesswork.

Run it the same way as snapshot.py (see README "Debugging"):

    import sys
    sys.path.append(r"C:\\path\\to\\...\\plugins\\susan_summary\\tools")
    import probe
    probe.run()

Prints, for the first track/layer/media it finds: every public attribute, its
type, and its value when cheap to read. Read-only -- touches nothing.
"""
from __future__ import print_function

__all__ = ["run"]

# Fields snapshot.py currently wants but hasn't confirmed on a real director.
WANTED = ("bStart", "bEnd", "tStart", "tEnd", "startBeat", "endBeat",
          "start", "end", "beatStart", "beatEnd", "module", "renderEnable",
          # v7: the layer's own identity. SuperLayer derives from Resource, so
          # `uid` should be there -- if it reads as None or as a method here,
          # every layer falls back to a derived id and the capture says so in
          # `idSource`.
          "uid", "path")


def _g(name):
    if name in globals():
        return globals()[name]
    try:
        import d3
    except BaseException:
        return None
    return getattr(d3, name, None)


def _dump(label, obj, limit=200):
    print("\n=== %s : %s ===" % (label, type(obj).__name__))
    if obj is None:
        print("  <none>")
        return
    names = [n for n in dir(obj) if not n.startswith("_")]
    print("  %d public members" % len(names))
    for name in sorted(names)[:limit]:
        try:
            val = getattr(obj, name)
        except BaseException as e:
            print("  %-28s <raised %s>" % (name, str(e)[:40]))
            continue
        kind = type(val).__name__
        if callable(val):
            print("  %-28s method" % name)
            continue
        text = ""
        try:
            text = repr(val)[:60]
        except BaseException:
            text = "<unreprable>"
        print("  %-28s %-18s %s" % (name, kind, text))


def _highlight(label, obj):
    """The specific fields snapshot.py depends on."""
    print("\n--- %s: fields snapshot.py wants ---" % label)
    for name in WANTED:
        try:
            if not hasattr(obj, name):
                print("  %-16s MISSING" % name)
                continue
            val = getattr(obj, name)
            print("  %-16s %-14s %s" % (name, type(val).__name__, repr(val)[:50]))
        except BaseException as e:
            print("  %-16s <raised %s>" % (name, str(e)[:40]))


def run():
    # Transport -> setlist -> first track -> first layer, same route snapshot.py takes.
    tm = None
    local_state = _g("LocalState")
    if local_state is not None:
        try:
            tm = local_state.localState().currentTransport
        except BaseException:
            pass
    if tm is None:
        try:
            tm = _g("guisystem").currentTransportManager
        except BaseException:
            pass
    if tm is None:
        print("no transport")
        return

    setlist = getattr(tm, "setList", None)
    tracks = list(getattr(setlist, "tracks", []) or [])
    # `name` came back None for both on the live run; snapshot.py falls back to
    # `description`, so show both here.
    print("transport=%r/%r setlist=%r/%r tracks=%d"
          % (getattr(tm, "name", None), getattr(tm, "description", None),
             getattr(setlist, "name", None), getattr(setlist, "description", None),
             len(tracks)))
    if not tracks:
        return

    track = tracks[0]
    _dump("Track", track)

    layers = list(getattr(track, "layers", []) or [])
    print("\ntrack has %d top-level layers" % len(layers))
    if not layers:
        return

    # Prefer a layer that has media -- more interesting than an empty one.
    layer = layers[0]
    for candidate in layers:
        try:
            seq = candidate.findSequence("video")
            if seq and getattr(seq, "sequence", None):
                layer = candidate
                break
        except BaseException:
            continue

    _dump("Layer", layer)
    _highlight("Layer", layer)
    _dump("Layer.module", getattr(layer, "module", None))

    # Where does the project path live?
    print("\n=== project paths candidates ===")
    for holder_name in ("state", "guisystem", "PathsManager"):
        holder = _g(holder_name)
        print("  %-14s %s" % (holder_name, type(holder).__name__ if holder is not None else "<absent>"))
        if holder is None:
            continue
        for attr in ("projectPaths", "paths", "projectFolder", "projectName"):
            try:
                if hasattr(holder, attr):
                    val = getattr(holder, attr)
                    got = val() if callable(val) else val
                    print("      .%-14s -> %s" % (attr, repr(got)[:70]))
            except BaseException as e:
                print("      .%-14s <raised %s>" % (attr, str(e)[:40]))

    # How do we actually get media off a sequence? evalResource(tStart) returns
    # None on some layers that plainly have keys, so compare both routes across
    # every layer -- this is the bug that silently emptied "media" arrays.
    print("\n=== media resolution, all layers ===")
    print("  %-22s %-10s %-6s %s" % ("layer", "keys", "eval", "module"))
    a_key = None
    a_media = None
    for candidate in layers:
        lname = getattr(candidate, "name", "?")
        mod = type(getattr(candidate, "module", None)).__name__
        try:
            fs = candidate.findSequence("video")
            seq = getattr(fs, "sequence", None) if fs else None
        except BaseException:
            seq = None
        if seq is None:
            print("  %-22s %-10s %-6s %s" % (lname[:22], "-", "-", mod))
            continue
        keys = list(getattr(seq, "keys", []) or [])
        try:
            ev = seq.evalResource(getattr(candidate, "tStart", 0.0))
        except BaseException as e:
            ev = "<raised %s>" % str(e)[:20]
        print("  %-22s %-10s %-6s %s"
              % (lname[:22], len(keys), "yes" if ev else "NONE", mod))
        if keys and a_key is None:
            a_key = keys[0]
        if ev and a_media is None:
            a_media = ev

    # KeyResource: which attribute holds the media resource?
    _dump("KeyResource", a_key)
    if a_key is not None:
        print("\n--- KeyResource: candidate payload attributes ---")
        for attr in ("resource", "value", "v", "r", "res", "t", "time", "path"):
            try:
                if hasattr(a_key, attr):
                    val = getattr(a_key, attr)
                    print("  %-12s %-20s %s" % (attr, type(val).__name__, repr(val)[:50]))
                else:
                    print("  %-12s MISSING" % attr)
            except BaseException as e:
                print("  %-12s <raised %s>" % (attr, str(e)[:40]))

    # A real media resource, to confirm regionSet (one was just added to a layer).
    _dump("media resource", a_media)
    if a_media is not None:
        print("\n--- media resource: fields snapshot.py wants ---")
        for attr in ("description", "path", "enabledVersion", "hasAudio",
                     "regionSet", "regionSets", "name"):
            try:
                if hasattr(a_media, attr):
                    val = getattr(a_media, attr)
                    print("  %-16s %-20s %s" % (attr, type(val).__name__, repr(val)[:50]))
                    if attr.startswith("regionSet") and val is not None:
                        _dump("  regionSet detail", val, limit=40)
                else:
                    print("  %-16s MISSING" % attr)
            except BaseException as e:
                print("  %-16s <raised %s>" % (attr, str(e)[:40]))
