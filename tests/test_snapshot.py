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


class Track(object):
    def __init__(self, description, layers, length=120.0):
        self.description = description
        self.layers = layers
        self.lengthInSec = length
        self.lengthInBeats = length * 2
        self.bpm = 120.0

    def globalTimeToBeat(self, t):
        """Beats aren't readable off layers; they come from the track."""
        return t * 2


class TM(object):
    def __init__(self, name, tracks):
        self.name = name
        self.setList = type("SL", (), {"name": "Main Setlist", "tracks": tracks})()


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
])
track2 = Track("Song 2", [])  # empty track

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
ok &= check("transport", snap["transport"] == "default", repr(snap["transport"]))
ok &= check("setlist", snap["setlist"] == "Main Setlist", repr(snap["setlist"]))
ok &= check("2 tracks", snap["trackCount"] == 2)

t1 = snap["tracks"][0]
names = [l["name"] for l in t1["layers"]]
ok &= check("flattens groups (6 layers)", len(t1["layers"]) == 6, str(names))
ok &= check("layerCount matches", t1["layerCount"] == len(t1["layers"]))
ok &= check("nested group path",
            [l["groupPath"] for l in t1["layers"] if l["name"] == "Deep"] == [["Backdrops", "Inner"]],
            str([l["groupPath"] for l in t1["layers"]]))
ok &= check("disabled layer kept, flagged",
            any(l["name"] == "Muted" and l["renderEnable"] is False for l in t1["layers"]))
ok &= check("empty track ok", snap["tracks"][1]["layers"] == [])

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

print("\n== file written ==")
path = snap["writtenTo"]
ok &= check("path under logs/", path and "logs" in path, repr(path))
ok &= check("file exists", path and os.path.isfile(path))
if path and os.path.isfile(path):
    text = open(path).read()
    ok &= check("valid json on disk", json.loads(text)["trackCount"] == 2)
    # Regression: the first live run wrote files that all claimed
    # "writtenTo": null, because the dict was serialised before the field was
    # set. The saved log must name itself.
    ok &= check("on-disk copy names itself", json.loads(text)["writtenTo"] == path,
                repr(json.loads(text)["writtenTo"]))
    ok &= check("indented + sorted (diffable)",
                "\n  " in text and text.index('"capturedAt"') < text.index('"project"'))

print("\n== named transport ==")
snap2 = snapshot.capture("default")
ok &= check("resolves by name", snap2["error"] is None and snap2["trackCount"] == 2)
snap3 = snapshot.capture("nope")
ok &= check("missing transport -> error, no crash", snap3["error"] == "no transport resolved", repr(snap3["error"]))

print("\n== no setlist ==")
bare = TM("bare", [])
bare.setList = None
install(bare, tmpdir)
snap4 = snapshot.capture()
ok &= check("no setlist -> error", snap4["error"] == "transport has no setlist", repr(snap4["error"]))

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
ok &= check("traversal still returns", snap6["trackCount"] == 2)
ok &= check("writtenTo None, no crash", snap6["writtenTo"] is None, repr(snap6["writtenTo"]))
ok &= check("failure recorded in debug", any("write failed" in d for d in snap6["debug"]), str(snap6["debug"]))

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
