/**
 * fit-stitch in a Web Worker.
 *
 * Runs the real Python library under Pyodide so the page never uploads
 * anything: a FIT file carries a GPS trace of where someone lives and rides,
 * and here it is only ever read by the tab the user dropped it into.
 *
 * The main thread stays free, which matters because merging a long ride takes
 * a few seconds of solid CPU. Progress arrives as it happens rather than as a
 * spinner.
 *
 * Framework-agnostic on purpose — this file is the whole client, and the UI
 * around it (the demo page here, a Vue component in the website) only sends
 * these messages and renders what comes back:
 *
 *   in   { type: 'init',     baseUrl }
 *        { type: 'merge',    files: [{ name, buffer }], tcx }
 *        { type: 'validate', file: { name, buffer } }
 *
 *   out  { type: 'ready',    engine }
 *        { type: 'progress', line }
 *        { type: 'done',     result }
 *        { type: 'error',    message }
 */

let pyodide = null;
let api = null;
let booting = null;

/** Resolve asset URLs against the base the page told us to use. */
const at = (baseUrl, path) => new URL(path, baseUrl).href;

async function boot(baseUrl) {
  const { loadPyodide } = await import(at(baseUrl, "pyodide/pyodide.mjs"));
  pyodide = await loadPyodide({ indexURL: at(baseUrl, "pyodide/") });

  // fit-stitch and both its dependencies are pure-Python wheels with no
  // dependencies of their own, so unpacking them into site-packages is a
  // complete install. That skips micropip and any network call at runtime.
  const site = pyodide.runPython("import site; site.getsitepackages()[0]");
  const manifest = await (await fetch(at(baseUrl, "wheels/manifest.json"))).json();
  for (const wheel of manifest.wheels) {
    const response = await fetch(at(baseUrl, `wheels/${wheel}`));
    if (!response.ok) throw new Error(`could not load ${wheel} (${response.status})`);
    pyodide.unpackArchive(await response.arrayBuffer(), "zip", { extractDir: site });
  }

  api = pyodide.pyimport("fit_stitch.web");
  return manifest.engine;
}

/** Boot once, even if several messages arrive before it finishes. */
function ready(baseUrl) {
  if (!booting) booting = boot(baseUrl);
  return booting;
}

/**
 * Convert a Python result into plain JS, and collect its byte arrays so they
 * can be transferred to the main thread instead of copied.
 */
function unwrap(proxy) {
  const result = proxy.toJs({ dict_converter: Object.fromEntries });
  proxy.destroy();
  const transfers = [];
  for (const value of Object.values(result)) {
    if (value instanceof Uint8Array) transfers.push(value.buffer);
  }
  return { result, transfers };
}

async function merge({ baseUrl, files, tcx }) {
  await ready(baseUrl);
  const onProgress = (line) => self.postMessage({ type: "progress", line });
  const pyFiles = pyodide.toPy(files.map((f) => [f.name, new Uint8Array(f.buffer)]));
  try {
    return unwrap(api.merge_bytes.callKwargs(pyFiles, { tcx: !!tcx, on_progress: onProgress }));
  } finally {
    pyFiles.destroy();
  }
}

async function validate({ baseUrl, file }) {
  await ready(baseUrl);
  return unwrap(api.validate_bytes(file.name, pyodide.toPy(new Uint8Array(file.buffer))));
}

self.onmessage = async (event) => {
  const message = event.data;
  try {
    if (message.type === "init") {
      self.postMessage({ type: "ready", engine: await ready(message.baseUrl) });
      return;
    }
    const { result, transfers } =
      message.type === "merge" ? await merge(message) : await validate(message);
    self.postMessage({ type: "done", result }, transfers);
  } catch (error) {
    // Boot failures must not wedge the worker: let the next message retry.
    if (message.type === "init" || !api) booting = null;
    self.postMessage({ type: "error", message: String((error && error.message) || error) });
  }
};
