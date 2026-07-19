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
  let pickerFailure = null

  // Show a real Save As dialog where the API exists. A plain `download`
  // attribute saves silently to the browser's download folder, which gives the
  // operator no say in where the log lands.
  if (window.showSaveFilePicker) {
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: name,
        types: [{ description: 'JSON snapshot', accept: { 'application/json': ['.json'] } }],
      })
      const writable = await handle.createWritable()
      await writable.write(text)
      await writable.close()
      setStatus(`Saved to ${handle.name}`, 'ok')
      return
    } catch (error) {
      // Cancelling the dialog is a decision, not a failure -- don't then go and
      // download the file anyway.
      if (error.name === 'AbortError') {
        setStatus('Save cancelled', '')
        return
      }
      // Anything else (API blocked in an embedded browser, blocked in a
      // cross-origin iframe, permissions) falls through to the download below --
      // but say why, otherwise a silently-missing dialog is unexplainable.
      pickerFailure = `${error.name}: ${error.message}`
    }
  } else {
    pickerFailure = 'showSaveFilePicker unavailable'
  }
  if (pickerFailure) {
    console.warn('Save As dialog unavailable —', pickerFailure,
      '| in iframe:', window.self !== window.top,
      '| secure context:', window.isSecureContext)
  }

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
  // Designer's plugin launcher embeds plugins in a sandboxed iframe without
  // allow-downloads, so the click above may do nothing at all and the clipboard
  // API is blocked too. Detect that and show the JSON for manual copying --
  // the only export that survives in there.
  const blocked = window.self !== window.top
  try {
    await navigator.clipboard.writeText(text)
    setStatus(`Downloading ${name} — also copied to clipboard`, 'ok')
  } catch {
    if (blocked) {
      showRawJson(text, name)
      return
    }
    setStatus(`Downloading ${name}`, 'ok')
  }
}

/** Last-resort export for the plugin launcher, whose sandbox blocks downloads,
 * the file picker and the clipboard alike: put the JSON on screen, selected,
 * so Ctrl+C works. The director-side log file is unaffected by any of this. */
function showRawJson(text, name) {
  const existing = document.getElementById('raw')
  if (existing) existing.remove()

  const wrap = document.createElement('div')
  wrap.id = 'raw'
  const note = document.createElement('p')
  note.className = 'sub'
  note.textContent =
    `This plugin window blocks downloads, so ${name} could not be saved from here. ` +
    'The snapshot is already written on the director (see the path above). ' +
    'Press Ctrl+C to copy the JSON below, or open this plugin directly in a browser to download it.'
  const area = document.createElement('textarea')
  area.readOnly = true
  area.value = text
  wrap.append(note, area)
  els.status.after(wrap)
  area.focus()
  area.select()
  setStatus(`Could not download ${name} — copy it below`, 'err')
}

// --- rendering --------------------------------------------------------------

const secs = (n) => (typeof n === 'number' ? `${n.toFixed(2)}s` : '—')

function render(snapshot) {
  const transports = snapshot.transports || []
  const allTracks = transports.flatMap((t) => t.tracks || [])
  const layerCount = allTracks.reduce((n, t) => n + (t.layerCount || 0), 0)

  els.summary.hidden = false
  els.summary.innerHTML = ''
  const facts = [
    ['Project', snapshot.project],
    ['Scope', snapshot.scope === 'all' ? 'all transports' : snapshot.scope],
    ['Transports', snapshot.transportCount],
    ['Tracks', allTracks.length],
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
    els.tracks.append(renderTransport(transport, transports.length > 1))
  }
}

/** A transport heading with its tracks. With only one transport the heading
 * would be redundant chrome, so the tracks are shown directly. */
function renderTransport(transport, showHeading) {
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
  for (const track of transport.tracks || []) {
    wrap.append(renderTrack(track))
  }
  return wrap
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
