import fs from 'node:fs'
import { pathToFileURL } from 'node:url'

const [sourcePath, typescriptPath, hostSourcePath] = process.argv.slice(2)
if (!sourcePath || !typescriptPath || !hostSourcePath) {
  throw new Error(
    'Usage: node arkui_renderer_performance.mjs RENDERER_SOURCE TYPESCRIPT_JS HOST_SOURCE',
  )
}

const imported = await import(pathToFileURL(typescriptPath))
const ts = imported.default ?? imported
const source = fs.readFileSync(sourcePath, 'utf8')
const javascript = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
  fileName: sourcePath,
}).outputText
const module = { exports: {} }
new Function('exports', 'module', 'require', javascript)(
  module.exports,
  module,
  () => {
    throw new Error('ArkUiRenderer must only have type imports')
  },
)
const { ArkUiRenderer } = module.exports

const nodeCount = 240
const sampleCount = 500
const operationsPerSample = 20
const changedIndex = Math.floor(nodeCount / 2)

function tree(revision) {
  return {
    type: 'Column',
    id: 1,
    revision,
    props: {},
    events: [],
    children: Array.from({ length: nodeCount }, (_, index) => ({
      type: 'Text',
      id: index + 2,
      revision: index === changedIndex ? revision : 1,
      props: {
        text: index === changedIndex ? `Dynamic ${revision}` : `Stable node ${index}`,
      },
      events: index === changedIndex ? ['tap'] : [],
      children: [],
    })),
  }
}

function patch(revision, rootId = 1, nodeId = changedIndex + 2) {
  return {
    wireVersion: 2,
    operation: 'patch',
    structureChanged: false,
    rootId,
    rootType: 'Column',
    rootRevision: revision,
    changed: [nodeId],
    nodes: [{
      type: 'Text',
      id: nodeId,
      revision,
      props: { text: `Dynamic ${revision}` },
      events: ['tap'],
      children: [],
    }],
    revisions: [
      { id: rootId, revision },
      { id: nodeId, revision },
    ],
  }
}

class Host {
  calls = []

  replace(root, changed, structureChanged) {
    this.calls.push({ root, changed, structureChanged })
  }
}

class Factory {
  nodes = new Map()
  creates = 0
  reuses = 0
  updates = 0
  touches = 0

  reuse(node) {
    const existing = this.nodes.get(node.id)
    if (existing?.type === node.type && existing.revision === node.revision) {
      this.reuses += 1
      return existing
    }
    return undefined
  }

  update(node, emit) {
    const existing = this.nodes.get(node.id)
    if (!existing || existing.type !== node.type) return undefined
    existing.model = node
    existing.revision = node.revision
    existing.emit = emit
    this.updates += 1
    return existing
  }

  touch(node) {
    const existing = this.nodes.get(node.id)
    if (existing?.type !== node.type) return
    existing.model = node
    existing.revision = node.revision
    this.touches += 1
  }

  touchRevision(nodeId, revision) {
    const existing = this.nodes.get(nodeId)
    if (!existing) return
    existing.revision = revision
    this.touches += 1
  }

  create(node, children, emit) {
    const existing = this.nodes.get(node.id)
    const rendered = existing ?? { type: node.type }
    rendered.model = node
    rendered.revision = node.revision
    rendered.children = children
    rendered.emit = emit
    this.nodes.set(node.id, rendered)
    this.creates += 1
    return rendered
  }
}

function check(condition, message) {
  if (!condition) throw new Error(message)
}

function percentile(samples, value) {
  const sorted = [...samples].sort((left, right) => left - right)
  return sorted[Math.min(Math.floor(sorted.length * value), sorted.length - 1)]
}

function timed(operation) {
  const started = process.hrtime.bigint()
  operation()
  return Number(process.hrtime.bigint() - started) / 1000
}

const host = new Host()
const factory = new Factory()
const renderer = new ArkUiRenderer(host, factory)
let sink = 0
renderer.replaceBatch(
  { operation: 'replace', structureChanged: true, changed: [], root: tree(1) },
  () => { sink = 1 },
)
check(factory.creates === nodeCount + 1, 'initial ArkUI tree was not created exactly once')
const initialCreates = factory.creates
renderer.replaceBatch(
  patch(2),
  () => { sink = 2 },
)
check(factory.creates === initialCreates, 'incremental ArkUI commit recreated a native node')
check(factory.updates === 1, 'incremental ArkUI commit did not update exactly one node')
check(factory.touches === 1, 'incremental ArkUI commit did not propagate the root revision')
check(host.calls.at(-1).changed.length === 1, 'ArkUI host did not receive one changed node')
check(host.calls.at(-1).structureChanged === false, 'ArkUI host received a structural update')

renderer.replaceBatch(
  patch(2),
  () => { sink = 3 },
)
factory.nodes.get(changedIndex + 2).emit(changedIndex + 2, 'tap')
check(sink === 3, 'reused ArkUI event handler did not use the latest event sink')

const nestedTree = (revision) => ({
  type: 'Column',
  id: 1001,
  revision,
  props: {},
  events: [],
  children: [{
    type: 'Column',
    id: 1002,
    revision,
    props: {},
    events: [],
    children: [{
      type: 'Text',
      id: 1003,
      revision,
      props: { text: `${revision}` },
      events: [],
      children: [],
    }],
  }],
})
const nestedFactory = new Factory()
const nestedRenderer = new ArkUiRenderer(new Host(), nestedFactory)
nestedRenderer.replaceBatch(
  { operation: 'replace', structureChanged: true, changed: [], root: nestedTree(1) },
  () => {},
)
nestedRenderer.replaceBatch(
  {
    wireVersion: 2,
    operation: 'patch',
    structureChanged: false,
    rootId: 1001,
    rootType: 'Column',
    rootRevision: 2,
    changed: [1003],
    nodes: [nestedTree(2).children[0].children[0]],
    revisions: [
      { id: 1001, revision: 2 },
      { id: 1002, revision: 2 },
      { id: 1003, revision: 2 },
    ],
  },
  () => {},
)
check(nestedFactory.updates === 1, 'nested ArkUI leaf was not updated exactly once')
check(nestedFactory.touches === 2, 'nested ArkUI ancestor revisions did not propagate')
check(
  nestedFactory.nodes.get(1001).revision === 2 &&
    nestedFactory.nodes.get(1002).revision === 2,
  'nested ArkUI parent keys remained stale',
)

const batches = Array.from({ length: 97 }, (_, index) => ({
  ...patch(index + 3),
}))
const fullNodes = tree(1).children.map((node) => ({ text: node.props.text }))
for (let index = 0; index < 20; index += 1) {
  renderer.replaceBatch(batches[index], () => {})
  fullNodes.forEach((node, nodeIndex) => {
    node.text = nodeIndex === changedIndex ? `Dynamic ${index}` : `Stable node ${nodeIndex}`
  })
}
const exact = []
const full = []
for (let sample = 0; sample < sampleCount; sample += 1) {
  const measureExact = () => {
    for (let operation = 0; operation < operationsPerSample; operation += 1) {
      const index = (sample * operationsPerSample + operation + 20) % batches.length
      renderer.replaceBatch(batches[index], () => {})
    }
  }
  const measureFull = () => {
    for (let operation = 0; operation < operationsPerSample; operation += 1) {
      fullNodes.forEach((node, index) => {
        node.text = index === changedIndex ? `Dynamic ${sample}` : `Stable node ${index}`
      })
    }
  }
  if (sample % 2 === 0) {
    exact.push(timed(measureExact) / operationsPerSample)
    full.push(timed(measureFull) / operationsPerSample)
  } else {
    full.push(timed(measureFull) / operationsPerSample)
    exact.push(timed(measureExact) / operationsPerSample)
  }
}
const report = {
  environment: 'Node host regression using DevEco TypeScript',
  nodes: nodeCount,
  samples: sampleCount,
  unit: 'microseconds',
  exactChanged: {
    median: percentile(exact, 0.5),
    p95: percentile(exact, 0.95),
  },
  fullNativeRebind: {
    median: percentile(full, 0.5),
    p95: percentile(full, 0.95),
  },
}
check(
  report.exactChanged.p95 < report.fullNativeRebind.p95,
  `ArkUI exact changed p95 regressed: ${JSON.stringify(report)}`,
)
console.log(`PvmHarmonyRenderBenchmark ${JSON.stringify(report)}`)

const queuedTasks = []
const taskpool = {
  execute(operation, json) {
    let resolve
    let reject
    const promise = new Promise((accept, fail) => {
      resolve = accept
      reject = fail
    })
    queuedTasks.push({
      finish: () => {
        try {
          resolve(operation(json))
        } catch (error) {
          reject(error)
        }
      },
      reject,
    })
    return promise
  },
}
const hostSource = fs
  .readFileSync(hostSourcePath, 'utf8')
  .replace(/^@Concurrent\s*$/m, '')
  .replace('class NativeCallbackAdapter', 'export class NativeCallbackAdapter')
const hostJavascript = ts.transpileModule(hostSource, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
  fileName: hostSourcePath,
}).outputText
const hostModule = { exports: {} }
new Function('exports', 'module', 'require', hostJavascript)(
  hostModule.exports,
  hostModule,
  (name) => {
    if (name === '@kit.ArkTS') return { taskpool }
    if (name === 'libpvm_harmony.so') return {}
    throw new Error(`Unexpected PvmRuntimeHost import ${name}`)
  },
)
const { NativeCallbackAdapter } = hostModule.exports
const delivered = []
const failures = []
const adapter = new NativeCallbackAdapter(
  {
    replaceTree: () => {},
    replaceBatch: (batch) => delivered.push(batch.root?.revision ?? batch.rootRevision),
  },
  {},
  {},
)
adapter.attach({
  dispatch: () => {},
  recordUiFailure: (error) => failures.push(`${error}`),
})
const largeBatch = (revision) => JSON.stringify({
  ...(revision === 1 ? {
    wireVersion: 2,
    operation: 'replace',
    structureChanged: true,
    changed: [],
    root: {
      type: 'Column',
      id: 1,
      revision,
      props: { padding: 'x'.repeat(33 * 1024) },
      events: [],
      children: [{
        type: 'Text',
        id: 2,
        revision,
        props: { text: `${revision}` },
        events: [],
        children: [],
      }],
    },
  } : {
    wireVersion: 2,
    operation: 'patch',
    structureChanged: false,
    changed: [2],
    rootId: 1,
    rootType: 'Column',
    rootRevision: revision,
    nodes: [{
      type: 'Text',
      id: 2,
      revision,
      props: { text: `${revision}${'x'.repeat(33 * 1024)}` },
      events: [],
      children: [],
    }],
    revisions: [
      { id: 1, revision },
      { id: 2, revision },
    ],
  }),
})
adapter.onUi(largeBatch(1))
adapter.onUi(largeBatch(2))
check(queuedTasks.length === 1, 'Harmony backpressure started duplicate decode workers')
queuedTasks[0].finish()
await new Promise((resolve) => setImmediate(resolve))
check(delivered.length === 0, 'stale Harmony decode overwrote the latest UI state')
check(queuedTasks.length === 2, 'latest Harmony batch was not decoded after stale work')
queuedTasks[1].finish()
await new Promise((resolve) => setImmediate(resolve))
check(delivered.length === 1 && delivered[0] === 2, 'latest Harmony batch was not committed')

adapter.onUi(largeBatch(3))
check(queuedTasks.length === 3, 'Harmony decode worker did not restart')
adapter.cancelUi()
queuedTasks[2].finish()
await new Promise((resolve) => setImmediate(resolve))
check(delivered.length === 1, 'closed Harmony host accepted a late UI batch')
adapter.onUi(`{${'x'.repeat(33 * 1024)}`)
check(queuedTasks.length === 4, 'invalid Harmony batch did not enter background decoding')
queuedTasks[3].finish()
await new Promise((resolve) => setImmediate(resolve))
check(failures.length === 1, 'Harmony background decode failure was swallowed')
console.log('PvmHarmonyBackpressureCheck PASS')
