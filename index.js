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

let registered = false
let lastSnapshot = null

const $ = (id) => document.getElementById(id)
const els = {
  capture: $('capture'),
  transport: $('transport'),
  refresh: $('refresh'),
  download: $('download'),
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
    const active = document.createElement('option')
    active.value = ''
    active.textContent = result.current
      ? `Active transport (${result.current})`
      : 'Active transport'
    els.transport.append(active)

    for (const name of result.transports || []) {
      const option = document.createElement('option')
      option.value = name
      option.textContent = name === result.current ? `${name} — active` : name
      els.transport.append(option)
    }
    if (previous && result.transports?.includes(previous)) {
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
    const arg = transport ? JSON.stringify(transport) : ''
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

    lastSnapshot = snapshot
    els.download.disabled = false
    render(snapshot)

    if (snapshot.error) {
      setStatus(snapshot.error, 'err')
    } else if (snapshot.writtenTo) {
      setStatus(`Saved to ${snapshot.writtenTo}`, 'ok')
    } else {
      // The traversal worked but the director couldn't write — the operator can
      // still keep the log via the download button.
      setStatus('Captured, but the log file could not be written. Use Download JSON.', 'err')
    }
  } catch (error) {
    setStatus(error.message, 'err')
  } finally {
    els.capture.disabled = false
  }
}

async function download() {
  if (!lastSnapshot) return
  const stamp = (lastSnapshot.capturedAt || '').replace(/:/g, '-') || 'snapshot'
  const name = `${stamp}_${lastSnapshot.project || 'project'}.json`
  const text = JSON.stringify(lastSnapshot, null, 2)
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  // The anchor must be in the document for the click to count, and the blob URL
  // must outlive the click -- revoking it synchronously cancels the download.
  // (Both were wrong before, which is why this button did nothing.)
  link.style.display = 'none'
  document.body.append(link)
  link.click()
  setTimeout(() => {
    link.remove()
    URL.revokeObjectURL(url)
  }, 10_000)

  // Designer's embedded browser may block downloads outright, so offer the
  // clipboard as a fallback the operator can actually use.
  try {
    await navigator.clipboard.writeText(text)
    setStatus(`Downloading ${name} — also copied to clipboard`, 'ok')
  } catch {
    setStatus(`Downloading ${name}`, 'ok')
  }
}

// --- rendering --------------------------------------------------------------

const secs = (n) => (typeof n === 'number' ? `${n.toFixed(2)}s` : '—')

function render(snapshot) {
  const layerCount = (snapshot.tracks || []).reduce((n, t) => n + (t.layerCount || 0), 0)
  els.summary.hidden = false
  els.summary.innerHTML = ''
  const facts = [
    ['Project', snapshot.project],
    ['Transport', snapshot.transport],
    ['Setlist', snapshot.setlist],
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
  for (const track of snapshot.tracks || []) {
    els.tracks.append(renderTrack(track))
  }
}

function renderTrack(track) {
  const details = document.createElement('details')
  const summary = document.createElement('summary')
  summary.textContent = track.name || 'Untitled track'
  const count = document.createElement('span')
  count.className = 'count'
  count.textContent = `${track.layerCount} layers · ${secs(track.lengthInSec)}`
  summary.append(count)
  details.append(summary)

  const table = document.createElement('table')
  table.innerHTML =
    '<thead><tr><th>Layer</th><th>Type</th><th>Start</th><th>End</th><th>Media</th></tr></thead>'
  const tbody = document.createElement('tbody')
  for (const layer of track.layers || []) {
    tbody.append(renderLayer(layer))
  }
  table.append(tbody)
  details.append(table)
  return details
}

function renderLayer(layer) {
  const tr = document.createElement('tr')
  if (layer.renderEnable === false) tr.className = 'disabled-layer'

  const name = layer.groupPath?.length
    ? `${layer.groupPath.join(' / ')} / ${layer.name}`
    : layer.name

  const cells = [name, layer.type || '—', secs(layer.tStart), secs(layer.tEnd)]
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

els.capture.addEventListener('click', capture)
els.download.addEventListener('click', download)
els.refresh.addEventListener('click', loadTransports)

// Offer the real transport list up front rather than making the operator guess.
loadTransports()
