# A script to prewarm all layers in a project
# Requires the user to start the transport before running the script

# Drop this file into the project/plugins folder
# In the d3 console run:
# #C:\Users\robin.spooner\Documents\d3 projects\notch_load_test 
# import sys
# sys.path.append("{path_to_d3_project}/project/plugins")
# import prewarmAllLayers
# prewarmAllLayers.run()

import math
from d3 import state, GroupLayer, rp, TransportCMDTrackBeat, LocalState

def getLayerStartTime(layer, startTimes):
    if not layer.renderEnable:
        return

    if issubclass(type(layer), GroupLayer): # recurse inside group layers
        for sublayer in layer.layers:
            getLayerStartTime(sublayer, startTimes)
    else:
        startTimes.add(math.ceil(layer.tStart)) # round to the next highest 1s for cheap fuzzy deduplicating

def run():
    tm = LocalState.localState().currentTransport
    tracks = tm.setList.tracks
    issuedTimeOffset = 0
    
    for track in tracks:
        print("For track " + track.description)
        startTimes = set()
        for layer in track.layers:
            getLayerStartTime(layer, startTimes)

        for tStart in sorted(startTimes):
            print("Jumping to " + str(tStart))
            cmd = rp(TransportCMDTrackBeat.make(state, tm, track, tStart, track.transitionInfoAtBeat(tStart)))
            cmd.issuedTime += issuedTimeOffset
            tm.addCommand(cmd)
            delta = 2 # seconds between jumps
            issuedTimeOffset += delta
    print("This will take " + str(issuedTimeOffset) + " seconds to complete.")