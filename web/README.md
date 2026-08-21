# fit-stitch in the browser

Runs the real Python library client-side under [Pyodide](https://pyodide.org).
A FIT file is a GPS trace of where someone lives and rides, so the merge happens
in the user's own tab: nothing is uploaded, nothing is stored, and there is no
backend to secure, rate-limit or keep a retention policy for.

This directory holds everything the website needs, plus a demo page used to
develop and test it here.

```
web/
  worker.js        the whole client — boots Pyodide, runs the merge
  FitStitch.vue    Vue 3 component for the Nuxt site, wraps worker.js
  demo/            standalone page: the same worker, plain HTML and JS
  public/          build output (gitignored) — wheels/ and pyodide/
```

## Build the assets

```bash
cd web && npm install && cd ..
./scripts/build-web-assets.sh
```

That produces `web/public/`:

- `wheels/` — three pure-Python wheels (`fit_stitch`, `fit-tool`,
  `garmin-fit-sdk`, ~730 KB total) plus `manifest.json`. The dependency versions
  come from `poetry.lock`, so a deployed page matches a known-good CLI build.
- `pyodide/` — the runtime files `loadPyodide` fetches (~13 MB raw; the wasm
  gzips to about 3.4 MB, so serve it compressed). The version is pinned by
  `web/package-lock.json`.

The wheels are self-hosted rather than installed from PyPI at runtime. That
keeps the privacy claim literal — the page talks to no third party — and means
an upstream release cannot change what a deployed page runs.

## Try it locally

```bash
python3 -m http.server 8000 -d web
# then open http://localhost:8000/demo/
```

Pyodide will not run from a `file://` URL; it needs to be served over http.

## Test it

```bash
poetry run pytest -m web
```

Drives the demo page in Chromium: merge, comparison table, validation, download,
progress streaming, and the error path for overlapping activities. Browser tests
are excluded from the default `pytest` run.

## Put it on the site

1. Copy `web/public/wheels/` and `web/public/pyodide/` into the Nuxt site's
   `public/`, and `web/worker.js` to `public/worker.js`. Committing the wheels
   makes deploys reproducible; they are ~730 KB.
2. Drop `FitStitch.vue` in as `pages/apps/fit-stitch.vue` (or a component). It
   touches `Worker` and `URL.createObjectURL`, so render it client-side only:

   ```vue
   <ClientOnly><FitStitch /></ClientOnly>
   ```

   `baseUrl` (default `/`) and `workerUrl` (default `/worker.js`) are props, so a
   site that serves assets from a sub-path can point them elsewhere.

Three things usually decide whether this works first try:

**Content Security Policy.** Pyodide compiles WebAssembly and starts a worker.
The page needs `script-src 'wasm-unsafe-eval'` (older browsers want
`'unsafe-eval'`) and `worker-src 'self'`. A CSP that omits these is the most
common reason the page loads but never becomes ready — it shows up as a console
error, not as a visible failure.

**Compression.** Serve `pyodide.asm.wasm` gzipped or brotlied. Uncompressed it
is 9.6 MB; compressed it is about 3.4 MB.

**Analytics.** Do not send file names or sizes anywhere. The page's claim is
that the file never leaves the browser, and an analytics event carrying
`morning-ride-home.fit` quietly makes that untrue.

## How the worker is driven

```js
const worker = new Worker('/worker.js', { type: 'module' })

worker.postMessage({ type: 'init', baseUrl: '/' })
worker.postMessage(
  { type: 'merge', baseUrl: '/', files: [{ name, buffer }], tcx: false },
  [buffer],                       // transferred, not copied
)

worker.onmessage = ({ data }) => {
  // { type: 'ready',    engine }
  // { type: 'progress', line }
  // { type: 'done',     result }   result.ok === false carries a user-facing error
  // { type: 'error',    message }  the runtime itself failed
}
```

`result` on success holds `output` (the merged FIT as a `Uint8Array`), optional
`tcx`, `summary`, `comparison` (rows preformatted by `fit_stitch.report`, so the
UI never formats a unit itself) and `validation`.

## What it costs the user

Measured in Chromium on a 320 km ride split into two 20 000-record files:

| step | time |
| --- | --- |
| Pyodide boot | 2.8 s |
| install wheels | 0.2 s |
| import fit-stitch | 0.8 s |
| merge | 3.5 s |
| validate | 5.4 s |

Peak WebAssembly heap was 75 MB. The runtime download happens once and is then
cached by the browser, so a repeat visit pays only the last three rows.
