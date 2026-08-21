<!--
  fit-stitch as a Nuxt page or component.

  All the work happens in worker.js, which this file only sends messages to and
  renders the replies of. That is deliberate: the logic is covered by browser
  tests in the fit-stitch repo, so the part copied into the website stays thin
  enough to review at a glance.

  Deploy: copy worker.js to public/worker.js and the contents of web/public/
  (wheels/ and pyodide/) into the site's public/. See web/README.md.
-->
<template>
  <div class="fs">
    <div class="fs-panel">
      <div
        class="fs-drop"
        :class="{ over }"
        tabindex="0"
        role="button"
        aria-label="Choose FIT files"
        @click="picker?.click()"
        @keydown.enter="picker?.click()"
        @keydown.space.prevent="picker?.click()"
        @dragover.prevent="over = true"
        @dragleave="over = false"
        @drop.prevent="onDrop"
      >
        <p><strong>Drop your .fit files here</strong></p>
        <p>or click to choose — two or more, order does not matter</p>
      </div>
      <input ref="picker" type="file" accept=".fit" multiple hidden @change="onPick" />

      <ul v-if="chosen.length" class="fs-files">
        <li v-for="(file, i) in chosen" :key="`${file.name}-${i}`">
          <span class="fs-name">{{ file.name }}</span>
          <span class="fs-size">{{ Math.round(file.size / 1024) }} KB</span>
          <button class="fs-ghost" @click="chosen.splice(i, 1)">Remove</button>
        </li>
      </ul>

      <div class="fs-row">
        <button :disabled="chosen.length < 2 || busy" @click="merge">
          {{ busy ? 'Merging…' : 'Merge' }}
        </button>
        <button class="fs-ghost" :disabled="busy" @click="reset">Clear</button>
        <label class="fs-check"><input v-model="tcx" type="checkbox" /> also export TCX</label>
        <span class="fs-hint">{{ status }}</span>
      </div>
    </div>

    <div v-if="error" class="fs-panel">
      <div class="fs-error">{{ error }}</div>
    </div>

    <div v-if="lines.length" class="fs-panel">
      <h2>Progress</h2>
      <pre ref="logEl" class="fs-log">{{ lines.join('\n') }}</pre>
    </div>

    <div v-if="result" class="fs-panel">
      <h2>{{ headline }}</h2>
      <div class="fs-tablewrap">
        <table>
          <thead>
            <tr>
              <th></th>
              <th v-for="c in result.comparison.columns" :key="c">{{ c }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in result.comparison.rows" :key="row.label">
              <td>{{ row.label }}</td>
              <td v-for="(v, i) in row.values" :key="i">{{ v }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 class="fs-spaced">Validation</h2>
      <ul class="fs-checks">
        <li v-for="c in result.validation.checks" :key="c.name">
          <span class="fs-mark" :class="c.passed ? 'pass' : 'fail'">{{ c.passed ? '✓' : '✗' }}</span>
          {{ c.name }}
          <span v-if="c.detail" class="fs-detail">({{ c.detail }})</span>
        </li>
      </ul>

      <div class="fs-row">
        <button @click="save(result.output, result.output_name)">Download merged.fit</button>
        <button v-if="result.tcx" class="fs-ghost" @click="save(result.tcx, result.tcx_name)">
          Download merged.tcx
        </button>
      </div>

      <p class="fs-hint fs-spaced">
        Import it in Garmin Connect via <strong>Import Data</strong>. If the original
        activities already synced, delete them afterwards so totals are not counted twice.
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

// Where worker.js, wheels/ and pyodide/ are served from — the site's public root.
const props = defineProps({
  baseUrl: { type: String, default: '/' },
  workerUrl: { type: String, default: '/worker.js' },
})

const picker = ref(null)
const logEl = ref(null)
const chosen = ref([])
const lines = ref([])
const result = ref(null)
const error = ref('')
const status = ref('')
const busy = ref(false)
const over = ref(false)
const tcx = ref(false)
let worker = null

const headline = computed(() => {
  const s = result.value?.summary
  if (!s) return ''
  const np = s.normalized_power ? `, NP ${s.normalized_power} W` : ''
  return `Merged ${s.files} files: ${s.records} records, ${s.laps} laps, ${(
    s.total_distance / 1000
  ).toFixed(2)} km${np}`
})

function addFiles(list) {
  chosen.value.push(...[...list].filter((f) => f.name.toLowerCase().endsWith('.fit')))
}
const onDrop = (e) => {
  over.value = false
  addFiles(e.dataTransfer.files)
}
const onPick = (e) => {
  addFiles(e.target.files)
  e.target.value = ''
}

function reset() {
  chosen.value = []
  lines.value = []
  result.value = null
  error.value = ''
  status.value = ''
}

async function merge() {
  busy.value = true
  error.value = ''
  result.value = null
  lines.value = []
  status.value = 'loading the Python runtime…'

  const files = await Promise.all(
    chosen.value.map(async (f) => ({ name: f.name, buffer: await f.arrayBuffer() })),
  )
  worker.postMessage(
    { type: 'merge', baseUrl: props.baseUrl, files, tcx: tcx.value },
    files.map((f) => f.buffer),
  )
}

function save(bytes, name) {
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

watch(lines, () => nextTick(() => logEl.value && (logEl.value.scrollTop = logEl.value.scrollHeight)), {
  deep: true,
})

onMounted(() => {
  worker = new Worker(props.workerUrl, { type: 'module' })
  worker.onmessage = ({ data }) => {
    if (data.type === 'progress') {
      lines.value.push(data.line)
      status.value = 'merging…'
      return
    }
    if (data.type === 'ready') return
    busy.value = false
    if (data.type === 'error') {
      error.value = data.message
      status.value = ''
      return
    }
    if (!data.result.ok) {
      error.value = data.result.error
      status.value = ''
      return
    }
    result.value = data.result
    status.value = data.result.validation.ok ? 'done' : 'done — validation reported problems'
  }
  // Boot the runtime up front so the first merge does not pay for it.
  worker.postMessage({ type: 'init', baseUrl: props.baseUrl })
})

onBeforeUnmount(() => worker?.terminate())
</script>

<style scoped>
.fs { --fs-line: #e3e3df; --fs-muted: #6b6b66; --fs-ok: #17803d; --fs-bad: #c0392b; --fs-drop: #f4f6fb; }
@media (prefers-color-scheme: dark) {
  .fs { --fs-line: #2e322f; --fs-muted: #9a9a94; --fs-ok: #4ade80; --fs-bad: #f87171; --fs-drop: #1a1f26; }
}
.fs-panel { border: 1px solid var(--fs-line); border-radius: 12px; padding: 1.25rem; margin-bottom: 1.25rem; }
.fs-drop { border: 2px dashed var(--fs-line); border-radius: 12px; background: var(--fs-drop); padding: 2.25rem 1.25rem; text-align: center; cursor: pointer; }
.fs-drop.over { border-color: currentColor; }
.fs-drop p { margin: 0.35rem 0; color: var(--fs-muted); }
.fs-files { list-style: none; margin: 1rem 0 0; padding: 0; }
.fs-files li { display: flex; gap: 0.75rem; align-items: center; padding: 0.5rem 0.75rem; border: 1px solid var(--fs-line); border-radius: 8px; margin-bottom: 0.4rem; }
.fs-name { flex: 1; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9rem; }
.fs-size { color: var(--fs-muted); font-size: 0.85rem; }
.fs-row { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; margin-top: 1rem; }
.fs-check { display: flex; gap: 0.4rem; align-items: center; color: var(--fs-muted); font-size: 0.92rem; }
.fs-log { margin: 0; max-height: 13rem; overflow: auto; background: var(--fs-drop); border: 1px solid var(--fs-line); border-radius: 8px; padding: 0.75rem; font: 12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--fs-muted); white-space: pre-wrap; word-break: break-word; }
.fs-tablewrap { overflow-x: auto; }
.fs table { border-collapse: collapse; width: 100%; font-size: 0.92rem; }
.fs th, .fs td { padding: 0.45rem 0.7rem; text-align: right; border-bottom: 1px solid var(--fs-line); white-space: nowrap; }
.fs th:first-child, .fs td:first-child { text-align: left; color: var(--fs-muted); }
.fs tbody td:last-child, .fs thead th:last-child { color: var(--fs-ok); font-weight: 600; }
.fs-checks { list-style: none; padding: 0; margin: 0; column-width: 15rem; }
.fs-checks li { padding: 0.15rem 0; font-size: 0.92rem; }
.fs-mark { font-weight: 700; }
.fs-mark.pass { color: var(--fs-ok); }
.fs-mark.fail { color: var(--fs-bad); }
.fs-detail { color: var(--fs-muted); }
.fs-error { border-left: 3px solid var(--fs-bad); background: var(--fs-drop); padding: 0.75rem 1rem; border-radius: 6px; color: var(--fs-bad); }
.fs-hint { color: var(--fs-muted); font-size: 0.9rem; }
.fs h2 { font-size: 1.05rem; margin: 0 0 0.8rem; }
.fs-spaced { margin-top: 1.5rem; }
</style>
