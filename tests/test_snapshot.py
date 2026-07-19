"""Exercise snapshot.py against fake director objects.

The director globals aren't importable locally, so inject them into the module's
namespace -- the same approach ../d3plg_media_info uses in its unit tests.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import snapshot


# --- fake director objects ---------------------------------------------------

class GroupLayer(object):
    def __init__(self, name, layers):
        self.name = name
        self.layers = layers


class Media(object):
    def __init__(self, uid, name, path, audio=True):
        self.uid = uid
        self.description = name
        self.path = path + ".apx"
        self.enabledVersion = "v2"
        self.hasAudio = audio
        self.regionSet = type("RS", (), {"name": "RegionSet A"})()


class KeyResource(object):
    """A key in a ResourceSequence. Real ones hold the media on `.resource`."""
    def __init__(self, t, resource):
        self.t = t
        self.resource = resource


class Seq(object):
    """evalResource(t) -> whichever media the layer holds at t.

    `evals` mirrors the live director finding that some layers hold keys but
    return None from evalResource(tStart) -- set it False to reproduce that."""
    def __init__(self, by_time, evals=True):
        self.by_time = by_time
        self.evals = evals
        self.keys = [KeyResource(t, by_time[t]) for t in sorted(by_time)]

    def evalResource(self, t):
        if not self.evals:
            return None
        best = None
        for kt in sorted(self.by_time):
            if kt <= t:
                best = self.by_time[kt]
        return best if best is not None else self.by_time[min(self.by_time)]


class Module(object):
    """Layers are all class "Layer"; the module is what distinguishes them."""


class VariableVideoModule(Module):
    pass


class Layer(object):
    # Real layers carry no beat fields at all -- deliberately absent here.
    def __init__(self, name, tStart, tEnd, media_by_time=None, renderEnable=True,
                 evals=True):
        self.name = name
        self.tStart = tStart
        self.tEnd = tEnd
        self.renderEnable = renderEnable
        self.module = VariableVideoModule() if media_by_time else Module()
        self._seq = Seq(media_by_time, evals) if media_by_time else None

    def findSequence(self, field):
        if field != "video" or self._seq is None:
            return None
        return type("FS", (), {"sequence": self._seq})()


class BadLayer(Layer):
    @property
    def tStart(self):
        raise BaseException("director exploded")

    @tStart.setter
    def tStart(self, v):
        pass


class Tag(object):
    def __init__(self, text):
        self.text = text


class Cue(object):
    def __init__(self, note=None, section=False, tags=None):
        self.note = note
        self.section = section
        self._tags = tags or {}      # {tagType: text}


class Track(object):
    """`cues` maps beat -> Cue. `tc_at` is the beat of the timecode tag, if any;
    a track without one has no timecode at all (as on the real director, where
    beatToGlobalTime just echoes the track time back)."""
    def __init__(self, description, layers, length=120.0, cues=None, tc_at=None):
        self.description = description
        self.layers = layers
        self.lengthInSec = length
        self.lengthInBeats = length * 2
        self.bpm = 120.0
        self._cues = dict(cues or {})
        if tc_at is not None:
            cue = self._cues.setdefault(tc_at, Cue())
            cue._tags[0] = "1:00:00:0"   # tag type 0 is timecode
            self._tc_at = tc_at
        else:
            self._tc_at = None

    def timeToBeat(self, t):
        """Beats aren't readable off layers; they come from the track."""
        return t * 2

    def beatToTime(self, b):
        return b / 2.0

    def cueBeats(self):
        return sorted(self._cues)

    def cueAtBeat(self, b):
        return self._cues.get(b)

    def tagAtBeat(self, b, tag_type):
        cue = self._cues.get(b)
        if cue is None:
            return None
        text = cue._tags.get(tag_type)
        return Tag(text) if text else None

    def beatToSection(self, b):
        return sum(1 for beat in sorted(self._cues)
                   if beat < b and self._cues[beat].section)

    def beatToGlobalTime(self, beat, clock_type, limited):
        """With a timecode tag, 1 hour plus the offset past the tag; without
        one, the track time -- which is what the real director does."""
        if self._tc_at is None:
            return beat / 2.0
        return 3600.0 + (beat - self._tc_at) / 2.0


class Timecode(object):
    def fps(self):
        return 30.0


class TM(object):
    def __init__(self, name, tracks):
        self.name = name
        self.setList = type("SL", (), {"name": "Main Setlist", "tracks": tracks})()

    def beatToTimecode(self, beat):
        """Only used to read the frame rate off; the per-track conversion is
        what actually produces timecodes."""
        return Timecode()


class ProjectPaths(object):
    """The real ProjectPathsManager exposes these as *methods*, not properties
    -- the reason `project` came back null on the first live run."""
    def __init__(self, folder):
        self._folder = folder

    def projectFolder(self):
        return self._folder

    def projectName(self):
        return "SusanShow"


def install(tm, project_dir):
    # Simulate the registered-module context, which is the one that matters:
    # there __file__ is the literal string "d3_loader" rather than a path, so
    # the log dir is built from the project folder. Leaving the real __file__ in
    # place would make these tests write into the repo instead.
    snapshot.__file__ = "d3_loader"
    snapshot.GroupLayer = GroupLayer
    snapshot.guisystem = type("G", (), {"currentTransportManager": tm})()
    snapshot.state = type("S", (), {"projectPaths": ProjectPaths(project_dir)})()
    snapshot.resourceManager = type("RM", (), {
        "allResources": staticmethod(lambda t: [tm])})()
    snapshot.TransportManager = TM


# --- fixtures ----------------------------------------------------------------

clip_a = Media(1, "Opener", r"D:\media\opener.mov")
clip_b = Media(2, "Verse", r"D:\media\verse.mov", audio=False)

nested = GroupLayer("Backdrops", [
    Layer("Backdrop A", 0.0, 30.0, {0.0: clip_a}),
    GroupLayer("Inner", [Layer("Deep", 5.0, 10.0, {5.0: clip_b})]),
])
track1 = Track("Song 1", [
    Layer("Video 1", 0.0, 60.0, {0.0: clip_a, 30.0: clip_b}),  # swaps clips
    nested,
    Layer("Muted", 0.0, 5.0, {0.0: clip_a}, renderEnable=False),
    Layer("No media", 10.0, 12.0),
    # The live-director case: keys present, but evalResource returns None.
    Layer("Eval blind", 0.0, 60.0, {0.0: clip_a}, evals=False),
], cues={
    0.0: Cue(note="opening note", section=True),
    10.0: Cue(section=True),
    20.0: Cue(note="mid-show", tags={1: "2.34"}),
    30.0: Cue(),                      # bare cue: nothing to record
}, tc_at=10.0)
track2 = Track("Song 2", [])  # empty track, and no timecode tags

tmpdir = tempfile.mkdtemp()
tm = TM("default", [track1, track2])
install(tm, tmpdir)


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + (("  -- " + detail) if detail and not cond else ""))
    return cond


ok = True
print("\n== happy path ==")
snap = snapshot.capture()
ok &= check("no error", snap["error"] is None, repr(snap["error"]))
ok &= check("project", snap["project"] == "SusanShow", repr(snap["project"]))
ok &= check("scope defaults to all", snap["scope"] == "all", repr(snap["scope"]))
ok &= check("active transport reported", snap["activeTransport"] == "default",
            repr(snap["activeTransport"]))
tr0 = snap["transports"][0]
# Tracks live once at the top level; transports reference them by id.
tracks_by_id = {t["id"]: t for t in snap["tracks"]}
tr0_tracks = [tracks_by_id[i] for i in tr0["trackRefs"]]
ok &= check("transport", tr0["name"] == "default", repr(tr0["name"]))
ok &= check("setlist", tr0["setlist"] == "Main Setlist", repr(tr0["setlist"]))
ok &= check("2 track refs", tr0["trackCount"] == 2)

t1 = tr0_tracks[0]
names = [l["name"] for l in t1["layers"]]
ok &= check("flattens groups (6 layers)", len(t1["layers"]) == 6, str(names))
ok &= check("layerCount matches", t1["layerCount"] == len(t1["layers"]))
ok &= check("nested group path",
            [l["groupPath"] for l in t1["layers"] if l["name"] == "Deep"] == [["Backdrops", "Inner"]],
            str([l["groupPath"] for l in t1["layers"]]))
ok &= check("disabled layer kept, flagged",
            any(l["name"] == "Muted" and l["renderEnable"] is False for l in t1["layers"]))
ok &= check("empty track ok", tr0_tracks[1]["layers"] == [])

v1 = [l for l in t1["layers"] if l["name"] == "Video 1"][0]
ok &= check("both clips on swapping layer", len(v1["media"]) == 2, str(v1["media"]))
ok &= check(".apx stripped", v1["media"][0]["path"] == r"D:\media\opener.mov", v1["media"][0]["path"])
ok &= check("regionSet", v1["media"][0]["regionSet"] == "RegionSet A")
ok &= check("hasAudio false preserved", v1["media"][1]["hasAudio"] is False)
ok &= check("times", (v1["tStart"], v1["tEnd"]) == (0.0, 60.0))
nomedia = [l for l in t1["layers"] if l["name"] == "No media"][0]
ok &= check("layer with no video sequence", nomedia["media"] == [])

# Regression: a layer whose sequence holds keys but whose evalResource returns
# None must still report its media -- read off the keys, not just the eval.
blind = [l for l in t1["layers"] if l["name"] == "Eval blind"][0]
ok &= check("media found via keys when eval returns None",
            [m["name"] for m in blind["media"]] == ["Opener"], str(blind["media"]))

ok &= check("module type, not generic Layer", v1["type"] == "VariableVideoModule", v1["type"])
ok &= check("beats derived from track", (v1["bStart"], v1["bEnd"]) == (0.0, 120.0),
            str((v1["bStart"], v1["bEnd"])))

print("\n== timecode ==")
ok &= check("track with tc tags flagged", t1["hasTimecode"] is True, str(t1["hasTimecode"]))
ok &= check("fps reported", t1["fps"] == 30.0, repr(t1["fps"]))
# The tag sits at beat 10. Video 1 starts at beat 0 -- before the tag, so it has
# no timecode and must fall back to track time rather than claim 00:00:00.00.
ok &= check("first timecode beat reported", t1["firstTimecodeBeat"] == 10.0,
            repr(t1["firstTimecodeBeat"]))
ok &= check("no timecode before the tag", v1["tcStart"] is None, repr(v1["tcStart"]))
ok &= check("timecode after the tag", v1["tcEnd"] == "01:00:55.00", repr(v1["tcEnd"]))
# A layer starting exactly at the tag does get one.
at_tag = [l for l in t1["layers"] if l["name"] == "Deep"][0]
ok &= check("timecode at the tag beat", at_tag["tcStart"] == "01:00:00.00",
            repr(at_tag["tcStart"]))

t2 = tr0_tracks[1]
ok &= check("track without tc tags flagged", t2["hasTimecode"] is False, str(t2["hasTimecode"]))
ok &= check("no fps without timecode", t2["fps"] is None, repr(t2["fps"]))

print("\n== cues, sections and notes ==")
cues = t1["cues"]
ok &= check("bare cue omitted", len(cues) == 3, str([c["beat"] for c in cues]))
ok &= check("section flagged", [c["isSection"] for c in cues] == [True, True, False],
            str([c["isSection"] for c in cues]))
ok &= check("notes captured",
            [c["note"] for c in cues] == ["opening note", None, "mid-show"],
            str([c["note"] for c in cues]))
ok &= check("tags captured", cues[2]["tags"] == [{"type": "cue", "text": "2.34"}],
            str(cues[2]["tags"]))
ok &= check("tc tag captured", cues[1]["tags"] == [{"type": "tc", "text": "1:00:00:0"}],
            str(cues[1]["tags"]))
ok &= check("cue timecode", cues[1]["timecode"] == "01:00:00.00", repr(cues[1]["timecode"]))
ok &= check("no cue timecode before the tag", cues[0]["timecode"] is None,
            repr(cues[0]["timecode"]))
ok &= check("cue track time", cues[0]["t"] == 0.0, repr(cues[0]["t"]))
ok &= check("no cue timecode without tags", t2["cues"] == [], str(t2["cues"]))

print("\n== timestamps are local ==")
import re as _re
import time as _time
ca = snap["capturedAt"]
ok &= check("capturedAt carries a UTC offset",
            bool(_re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$", ca)), repr(ca))
# A UTC stamp filed an evening show under the next day; this must be local time.
ok &= check("capturedAt is local, not UTC",
            ca[:13] == _time.strftime("%Y-%m-%dT%H"), "%r vs local %r" % (ca, _time.strftime("%Y-%m-%dT%H")))
ok &= check("filename stamp derives from capturedAt",
            snapshot._stamp_from(ca) == ca[:19].replace(":", "-"), repr(snapshot._stamp_from(ca)))
ok &= check("stamp strips a positive offset",
            snapshot._stamp_from("2026-01-05T09:00:00+01:00") == "2026-01-05T09-00-00")
ok &= check("stamp survives a missing capturedAt",
            snapshot._stamp_from(None) == "snapshot")

print("\n== file written ==")
path = snap["writtenTo"]
ok &= check("path under logs/", path and "logs" in path, repr(path))
ok &= check("logs sit next to the plugin",
            path and path.replace("/", os.sep).startswith(
                os.path.join(tmpdir, "plugins", "susan_summary", "logs")), repr(path))
ok &= check("file exists", path and os.path.isfile(path))
if path and os.path.isfile(path):
    text = open(path).read()
    ok &= check("valid json on disk",
                json.loads(text)["transports"][0]["trackCount"] == 2)
    # Regression: the first live run wrote files that all claimed
    # "writtenTo": null, because the dict was serialised before the field was
    # set. The saved log must name itself.
    ok &= check("on-disk copy names itself", json.loads(text)["writtenTo"] == path,
                repr(json.loads(text)["writtenTo"]))
    ok &= check("indented + sorted (diffable)",
                "\n  " in text and text.index('"capturedAt"') < text.index('"project"'))

print("\n== scopes ==")
snap2 = snapshot.capture("default")
ok &= check("resolves by name",
            snap2["error"] is None and snap2["transports"][0]["trackCount"] == 2)
ok &= check("named scope recorded", snap2["scope"] == "default", repr(snap2["scope"]))
snap2b = snapshot.capture(active_only=True)
ok &= check("active_only scope", snap2b["scope"] == "active", repr(snap2b["scope"]))
ok &= check("active_only captures one", snap2b["transportCount"] == 1)
snap3 = snapshot.capture("nope")
ok &= check("missing transport -> error, no crash", snap3["error"] == "no transport resolved", repr(snap3["error"]))

# Default scope must capture *every* transport, not just the active one.
tm_b = TM("second", [Track("Other", [Layer("L", 0.0, 5.0, {0.0: clip_b})])])
snapshot.resourceManager = type("RM", (), {
    "allResources": staticmethod(lambda t: [tm, tm_b])})()
snap_all = snapshot.capture()
ok &= check("all scope captures every transport", snap_all["transportCount"] == 2,
            str([t["name"] for t in snap_all["transports"]]))
ok &= check("active transport listed first",
            snap_all["transports"][0]["name"] == "default",
            str([t["name"] for t in snap_all["transports"]]))
ok &= check("no duplicate of the active transport",
            [t["name"] for t in snap_all["transports"]] == ["default", "second"],
            str([t["name"] for t in snap_all["transports"]]))

print("\n== shared tracks are stored once ==")
# Both transports run the same two tracks, plus one unique to the second.
# Writing them inline duplicated the shared ones, so a single layer edit showed
# up as two identical diff hunks.
shared = Track("Shared", [Layer("L", 0.0, 5.0, {0.0: clip_a})])
only_b = Track("Only B", [Layer("M", 0.0, 5.0, {0.0: clip_b})])
tm_x = TM("x", [shared])
tm_y = TM("y", [shared, only_b])
install(tm_x, tmpdir)
snapshot.resourceManager = type("RM", (), {
    "allResources": staticmethod(lambda t: [tm_x, tm_y])})()
snap_dedupe = snapshot.capture()

ids = [t["id"] for t in snap_dedupe["tracks"]]
ok &= check("each track stored once", ids == ["Only B", "Shared"], str(ids))
ok &= check("trackCount counts unique tracks", snap_dedupe["trackCount"] == 2)
refs = {t["name"]: t["trackRefs"] for t in snap_dedupe["transports"]}
ok &= check("both transports reference the shared track",
            refs["x"] == ["Shared"] and refs["y"] == ["Shared", "Only B"], str(refs))
ok &= check("refs preserve setlist order", refs["y"] == ["Shared", "Only B"], str(refs))
ok &= check("every ref resolves",
            all(r in ids for t in snap_dedupe["transports"] for r in t["trackRefs"]))
# The payload is what must not duplicate: the shared track's layer and its media
# appear once, however many transports run it.
blob = json.dumps(snap_dedupe)
ok &= check("shared track's layer stored once", blob.count('"L"') == 1, str(blob.count('"L"')))
ok &= check("shared track's media stored once",
            blob.count('"Opener"') == 1, str(blob.count('"Opener"')))

# Same name, genuinely different track (different uid) must not be merged.
a = Track("Twin", [Layer("A", 0.0, 1.0)])
b = Track("Twin", [Layer("B", 0.0, 1.0)])
a.uid, b.uid = 101, 102
tm_t = TM("t", [a, b])
install(tm_t, tmpdir)
snap_twins = snapshot.capture()
twin_ids = [t["id"] for t in snap_twins["tracks"]]
ok &= check("same-named tracks kept separate", twin_ids == ["Twin", "Twin #2"], str(twin_ids))
ok &= check("both twins referenced",
            snap_twins["transports"][0]["trackRefs"] == ["Twin", "Twin #2"],
            str(snap_twins["transports"][0]["trackRefs"]))

print("\n== list_transports ==")
install(tm, tmpdir)
import io as _io
import contextlib as _contextlib
_buf = _io.StringIO()
with _contextlib.redirect_stdout(_buf):
    snapshot.list_transports()
tl = json.loads(_buf.getvalue())
ok &= check("no error", tl["error"] is None, repr(tl["error"]))
ok &= check("lists the transport", tl["transports"] == ["default"], str(tl["transports"]))
ok &= check("reports the active one", tl["current"] == "default", repr(tl["current"]))

print("\n== no setlist ==")
bare = TM("bare", [])
bare.setList = None
install(bare, tmpdir)
snap4 = snapshot.capture()
# The error is per-transport now: one transport without a setlist must not
# abort a capture that spans several.
ok &= check("no setlist -> per-transport error",
            snap4["transports"][0]["error"] == "transport has no setlist",
            repr(snap4["transports"][0]["error"]))
ok &= check("capture itself still succeeds", snap4["error"] is None, repr(snap4["error"]))

print("\n== bad layer degrades ==")
install(TM("t", [Track("Broken", [BadLayer("Bad", 0.0, 1.0)])]), tmpdir)
snap5 = snapshot.capture()
bad = snap5["tracks"][0]["layers"][0]
ok &= check("survives bad layer", snap5["error"] is None, repr(snap5["error"]))
# An unreadable field degrades to null; the layer is still logged with whatever
# else could be read. null is distinguishable from a real 0.0 in the JSON.
ok &= check("layer still logged", bad["name"] == "Bad", str(bad))
ok &= check("unreadable field -> null", bad["tStart"] is None, str(bad))
ok &= check("readable fields survive", bad["tEnd"] == 1.0, str(bad))

print("\n== unwritable log dir ==")
# A path with a NUL byte can't be created on any platform, so makedirs fails --
# exercising the "director couldn't write" branch the UI surfaces.
install(tm, "\0bad")
snap6 = snapshot.capture()
ok &= check("traversal still returns", snap6["transports"][0]["trackCount"] == 2)
ok &= check("writtenTo None, no crash", snap6["writtenTo"] is None, repr(snap6["writtenTo"]))
ok &= check("failure recorded in debug", any("write failed" in d for d in snap6["debug"]), str(snap6["debug"]))

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
