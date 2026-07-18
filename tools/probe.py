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
          "start", "end", "beatStart", "beatEnd", "module", "renderEnable")


def _g(name):
    if name in globals():
        return globals()[name]
    try:
        import d3
    except BaseException:
        return None
    return getattr(d3, name, None)


def _dump(label, obj, limit=80):
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
    print("transport=%r setlist=%r tracks=%d"
          % (getattr(tm, "name", None), getattr(setlist, "name", None), len(tracks)))
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

    # The media sequence, to confirm how to enumerate clip changes over time.
    try:
        seq = layer.findSequence("video").sequence
        _dump("video sequence", seq)
        media = seq.evalResource(getattr(layer, "tStart", 0.0))
        _dump("media resource", media)
    except BaseException as e:
        print("\nno video sequence on probed layer: %s" % e)
