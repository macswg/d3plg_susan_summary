// Drive the real plugin page in Chrome: click Capture, observe what renders.
//
// The only way to exercise index.js -- the Python side has tests/test_snapshot.py,
// but the UI needs a browser and a live director. Requires Designer running with
// the plugin served (see the nginx `location /projects` alias if it 404s).
//
//   npm i puppeteer-core          # drives your installed Chrome, downloads nothing
//   node tools/ui_test.js         # all transports (default scope)
//   node tools/ui_test.js @active
//   node tools/ui_test.js <transport-name>
//
// Writes ui-<scope>.png alongside, and exits non-zero on a page error.
const puppeteer = require('puppeteer-core')

const URL =
  process.env.PLUGIN_URL ||
  'http://localhost/projects/Plugins_Testing_Feb_2026/plugins/susan_summary/index.html'
const CHROME =
  process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-gpu'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1100, height: 900 })

  const errors = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push('console: ' + m.text())
  })
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
  page.on('requestfailed', (r) =>
    errors.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`))

  await page.goto(URL, { waitUntil: 'networkidle2' })

  const scope = process.argv[2] || ''
  await page.select('#transport', scope)

  await page.click('#capture')
  // Wait for the status line to settle into a result.
  await page.waitForFunction(
    () => {
      const s = document.getElementById('status')
      return s && s.textContent.trim() && !s.textContent.includes('Capturing')
    },
    { timeout: 90_000 },
  )

  const result = await page.evaluate(() => {
    const status = document.getElementById('status')
    return {
      status: status.textContent.trim(),
      statusClass: status.className,
      summary: [...document.querySelectorAll('#summary div')].map((d) => d.textContent),
      headings: [...document.querySelectorAll('.transport-heading')].map((h) => h.textContent),
      trackTitles: [...document.querySelectorAll('#tracks summary')].map((s) => s.textContent),
      layerRows: document.querySelectorAll('#tracks tbody tr').length,
      regionSets: [...document.querySelectorAll('#tracks td')]
        .map((td) => td.textContent)
        .filter((t) => t.includes('region')).length,
      downloadDisabled: document.getElementById('download').disabled,
    }
  })

  console.log('scope           :', scope || '(all)')
  console.log('status          :', result.status)
  console.log('status class    :', result.statusClass)
  console.log('summary         :', result.summary.join('  |  '))
  console.log('transport heads :', result.headings)
  console.log('tracks rendered :', result.trackTitles.length)
  result.trackTitles.forEach((t) => console.log('   -', t))
  console.log('layer rows      :', result.layerRows)
  console.log('download enabled:', !result.downloadDisabled)
  console.log('errors          :', errors.length ? errors : '(none)')

  await page.screenshot({ path: `ui-${scope.replace('@', '') || 'all'}.png`, fullPage: true })
  await browser.close()

  // A page error means the UI is broken even if something rendered.
  if (errors.length) process.exit(1)
})().catch((e) => {
  console.error('FAILED:', e.message)
  process.exit(1)
})
