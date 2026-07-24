// Susan Summary — drives snapshot.py on the director and renders the result.
//
// No build step: this file is served as-is from the plugin folder. It talks to
// the director's Python Execution API directly, the same way the relay in
// ../d3plg_media_info (server/director-poller.js) does:
//   POST /api/session/python/registermodule  {moduleName, contents}
//   POST /api/session/python/execute         {moduleName, script}
// and reads the result out of pythonLog / returnValue.

const MODULE_NAME = 'susan_summary'
const API = '/api/session/python'

// Bump on release. There's no build step to inject this, so it lives here as
// the single source -- keep it in step with the git tag.
const APP_VERSION = '2.0.0'

let registered = false

const $ = (id) => document.getElementById(id)
const els = {
  capture: $('capture'),
  transport: $('transport'),
  refresh: $('refresh'),
  status: $('status'),
  summary: $('summary'),
  tracks: $('tracks'),
}

function setStatus(message, kind = '') {
  els.status.textContent = message
  els.status.className = kind
}

/** Fail with the director's status rather than a bare "fetch failed" — this
 * string is what the operator sees. */
async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const code = `${res.status}${res.statusText ? ` ${res.statusText}` : ''}`
    // A 5xx from the gateway in front of the director means the director
    // process itself isn't answering — not a plugin bug.
    throw new Error(
      res.status >= 502 && res.status <= 504
        ? `Director not responding (${code})`
        : `Director error (${code})`,
    )
  }
  return res.json()
}

/** Register snapshot.py once per page load. */
async function register() {
  if (registered) return
  const res = await fetch('./snapshot.py')
  if (!res.ok) throw new Error('Could not read snapshot.py from the plugin folder')
  await post('/registermodule', { moduleName: MODULE_NAME, contents: await res.text() })
  registered = true
}

/** Populate the transport dropdown from the director. Keeps the current
 * selection if it still exists, so a refresh doesn't reset the operator. */
async function loadTransports() {
  const previous = els.transport.value
  try {
    await register()
    const data = await post('/execute', {
      moduleName: MODULE_NAME,
      script: 'list_transports()',
    })
    const raw = (data.pythonLog || data.returnValue || '').trim()
    const result = JSON.parse(raw)
    if (result.error) throw new Error(result.error)

    els.transport.innerHTML = ''
    const add = (value, label) => {
      const option = document.createElement('option')
      option.value = value
      option.textContent = label
      els.transport.append(option)
    }

    // Default is everything -- a state log should capture the whole showfile
    // unless the operator narrows it deliberately.
    const count = (result.transports || []).length
    add('', count ? `All transports (${count})` : 'All transports')
    add('@active', result.current ? `Active only (${result.current})` : 'Active only')
    for (const name of result.transports || []) {
      add(name, name === result.current ? `${name} — active` : name)
    }

    if (previous && [...els.transport.options].some((o) => o.value === previous)) {
      els.transport.value = previous
    }
  } catch (error) {
    setStatus(`Could not list transports: ${error.message}`, 'err')
  }
}

async function capture() {
  const transport = els.transport.value.trim()
  els.capture.disabled = true
  setStatus('Capturing…', 'busy')
  try {
    await register()
    // '' -> every transport (default), '@active' -> the active one, else by name.
    const arg =
      transport === '' ? '' : transport === '@active' ? 'active_only=True' : JSON.stringify(transport)
    const data = await post('/execute', {
      moduleName: MODULE_NAME,
      script: `capture(${arg})`,
    })
    // snapshot.py prints one JSON object; the director hands it back as the
    // captured stdout.
    const raw = (data.pythonLog || data.returnValue || '').trim()
    if (!raw) throw new Error('Director returned nothing — is snapshot.py registered?')

    let snapshot
    try {
      snapshot = JSON.parse(raw)
    } catch {
      throw new Error(`Unexpected director output: ${raw.slice(0, 200)}`)
    }

    render(snapshot)

    if (snapshot.error) {
      setStatus(snapshot.error, 'err')
    } else if (snapshot.writtenTo) {
      setStatus(`Saved to ${snapshot.writtenTo}`, 'ok')
    } else {
      // The traversal worked but the director couldn't write; debug says why.
      const why = (snapshot.debug || []).find((d) => d.startsWith('write failed'))
      setStatus(
        `Captured, but the log file could not be written${why ? ` — ${why}` : ''}`,
        'err',
      )
    }
  } catch (error) {
    setStatus(error.message, 'err')
  } finally {
    els.capture.disabled = false
  }
}

// --- rendering --------------------------------------------------------------

const secs = (n) => (typeof n === 'number' ? `${n.toFixed(2)}s` : '—')

function render(snapshot) {
  const transports = snapshot.transports || []
  // Tracks are stored once at the top level and referenced by id, so a track
  // shared by two transports isn't duplicated in the log.
  const byId = new Map((snapshot.tracks || []).map((t) => [t.id, t]))
  const layerCount = (snapshot.tracks || []).reduce((n, t) => n + (t.layerCount || 0), 0)

  els.summary.hidden = false
  els.summary.innerHTML = ''
  const facts = [
    ['Project', snapshot.project],
    ['Scope', snapshot.scope === 'all' ? 'all transports' : snapshot.scope],
    ['Transports', snapshot.transportCount],
    ['Tracks', snapshot.trackCount],
    ['Layers', layerCount],
    ['Captured', snapshot.capturedAt],
  ]
  for (const [label, value] of facts) {
    const div = document.createElement('div')
    div.textContent = `${label}: `
    const b = document.createElement('b')
    b.textContent = value === null || value === undefined || value === '' ? '—' : String(value)
    div.append(b)
    els.summary.append(div)
  }

  els.tracks.innerHTML = ''
  for (const transport of transports) {
    els.tracks.append(renderTransport(transport, transports.length > 1, byId))
  }
}

/** A transport heading with its tracks. With only one transport the heading
 * would be redundant chrome, so the tracks are shown directly. */
function renderTransport(transport, showHeading, byId) {
  const wrap = document.createElement('div')
  if (showHeading) {
    const heading = document.createElement('h2')
    heading.className = 'transport-heading'
    heading.textContent = transport.name || '(unnamed transport)'
    const meta = document.createElement('span')
    meta.textContent = transport.error
      ? ` — ${transport.error}`
      : ` — setlist ${transport.setlist || '(none)'}, ${transport.trackCount} tracks`
    heading.append(meta)
    wrap.append(heading)
  }
  // Resolve refs back to the shared track records; the app still shows each
  // transport's tracks separately even though the log stores them once.
  for (const id of transport.trackRefs || []) {
    const track = byId.get(id)
    if (track) wrap.append(renderTrack(track))
  }
  return wrap
}

function renderTrack(track) {
  const details = document.createElement('details')
  const summary = document.createElement('summary')
  summary.textContent = track.name || 'Untitled track'
  const count = document.createElement('span')
  count.className = 'count'
  const cues = track.cues || []
  const marks = cues.filter((c) => c.isSection).length
  count.textContent =
    `${track.layerCount} layers · ${secs(track.lengthInSec)}` +
    (marks ? ` · ${marks} sections` : '') +
    (track.hasTimecode ? ` · timecode @ ${track.fps}fps` : '')
  summary.append(count)
  details.append(summary)

  if (cues.length) details.append(renderCues(track, cues))

  const table = document.createElement('table')
  // Times read as timecode when the track has timecode tags, seconds otherwise.
  const unit = track.hasTimecode ? 'Timecode in' : 'Start'
  table.innerHTML =
    `<thead><tr><th>Layer</th><th>Type</th><th>${unit}</th><th>${
      track.hasTimecode ? 'Timecode out' : 'End'
    }</th><th>Media</th></tr></thead>`
  const tbody = document.createElement('tbody')
  for (const layer of track.layers || []) {
    tbody.append(renderLayer(layer, track))
  }
  table.append(tbody)
  details.append(table)
  return details
}

/** Section breaks, notes and tags — the show's structure, which layer timings
 * alone don't convey. */
function renderCues(track, cues) {
  const wrap = document.createElement('div')
  wrap.className = 'cues'
  const table = document.createElement('table')
  table.innerHTML = `<thead><tr><th>${
    track.hasTimecode ? 'Timecode' : 'Time'
  }</th><th>Section</th><th>Tags</th><th>Note</th></tr></thead>`
  const tbody = document.createElement('tbody')

  for (const cue of cues) {
    const tr = document.createElement('tr')
    const cells = [
      cue.timecode || secs(cue.t),
      cue.isSection ? `§ ${cue.section ?? ''}`.trim() : '',
      (cue.tags || []).map((t) => `${t.type.toUpperCase()} ${t.text}`).join(', '),
      cue.note || '',
    ]
    for (const [i, text] of cells.entries()) {
      const td = document.createElement('td')
      td.textContent = text
      if (i === 3 && text) td.className = 'note'
      tr.append(td)
    }
    tbody.append(tr)
  }
  table.append(tbody)
  wrap.append(table)
  return wrap
}

function renderLayer(layer, track) {
  const tr = document.createElement('tr')
  if (layer.renderEnable === false) tr.className = 'disabled-layer'

  const name = layer.groupPath?.length
    ? `${layer.groupPath.join(' / ')} / ${layer.name}`
    : layer.name

  // Prefer timecode; fall back to seconds where the track has no timecode tags.
  const start = (track?.hasTimecode && layer.tcStart) || secs(layer.tStart)
  const end = (track?.hasTimecode && layer.tcEnd) || secs(layer.tEnd)
  const cells = [name, layer.type || '—', start, end]
  for (const text of cells) {
    const td = document.createElement('td')
    td.textContent = text
    tr.append(td)
  }

  const media = document.createElement('td')
  if (layer.error) {
    media.className = 'muted'
    media.textContent = layer.error
  } else if (!layer.media?.length) {
    media.className = 'muted'
    media.textContent = '—'
  } else {
    for (const item of layer.media) {
      const wrap = document.createElement('div')
      wrap.textContent = item.name || '(unnamed)'
      if (item.path) {
        const path = document.createElement('div')
        path.className = 'path'
        path.textContent = item.path
        wrap.append(path)
      }
      media.append(wrap)
    }
  }
  tr.append(media)
  return tr
}

/** `f` expands every track, or collapses them all if they're already open.
 * Ignored while a control has focus, so it doesn't fight the transport
 * dropdown's own type-to-select. */
function toggleAllTracks(event) {
  if (event.key !== 'f' || event.ctrlKey || event.metaKey || event.altKey) return
  const target = event.target
  if (target?.closest?.('input, select, textarea') || target?.isContentEditable) return

  const tracks = [...document.querySelectorAll('#tracks details')]
  if (!tracks.length) return
  event.preventDefault()
  const expand = tracks.some((d) => !d.open)
  for (const details of tracks) details.open = expand
}

$('version').textContent = `v${APP_VERSION}`

document.addEventListener('keydown', toggleAllTracks)
els.capture.addEventListener('click', capture)
els.refresh.addEventListener('click', loadTransports)

// Offer the real transport list up front rather than making the operator guess.
loadTransports()
