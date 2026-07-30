import { common } from '@kit.AbilityKit'
import { UIContext } from '@kit.ArkUI'
import { fileIo as fs } from '@kit.CoreFileKit'
import { ArkUiNodeFactory, ArkUiRenderer, ArkUiViewHost } from './ArkUiRenderer'
import { installBasicHarmonyCapabilities } from './BasicHarmonyCapabilities'
import { HarmonyEd25519Verifier } from './HarmonyCrypto'
import { CapabilityRegistry, PvmRuntimeHost, UiNode } from './PvmRuntimeHost'

type Emit = (nodeId: number, event: string, value?: string) => void
type Replace = (root: PvmRenderedNode) => void

export interface PvmRuntimeSessionConfig {
  context: common.Context
  modulePath: string
  publicKeyPath: string
  statePath: string
  applicationId: string
  channel: string
  profile: string
  minimumRelease: number
  preferenceName?: string
}

export class PvmRenderedNode {
  model: UiNode
  children: PvmRenderedNode[]
  emit: Emit
  containsInput: boolean

  constructor(
    model: UiNode,
    children: PvmRenderedNode[],
    emit: Emit,
  ) {
    this.model = model
    this.children = children
    this.emit = emit
    this.containsInput =
      model.type === 'Input' || children.some((child) => child.containsInput)
  }

  update(model: UiNode, children: PvmRenderedNode[], emit: Emit): void {
    this.model = model
    this.children = children
    this.emit = emit
    this.containsInput =
      model.type === 'Input' || children.some((child) => child.containsInput)
  }
}

class CallbackViewHost implements ArkUiViewHost {
  private readonly replaceCallback: Replace
  private readonly factory: HarmonyNodeFactory

  constructor(replaceCallback: Replace, factory: HarmonyNodeFactory) {
    this.replaceCallback = replaceCallback
    this.factory = factory
  }

  replace(root: object): void {
    const rendered = root as PvmRenderedNode
    this.factory.retainNodes(rendered)
    this.replaceCallback(rendered)
  }
}

class HarmonyNodeFactory implements ArkUiNodeFactory {
  private readonly nodes: Map<number, PvmRenderedNode> = new Map()

  create(node: UiNode, children: object[], emit: Emit): object {
    const renderedChildren = children.map((child) => child as PvmRenderedNode)
    const existing = this.nodes.get(node.id)
    if (existing !== undefined && existing.model.type === node.type) {
      existing.update(node, renderedChildren, emit)
      return existing
    }
    const rendered = new PvmRenderedNode(node, renderedChildren, emit)
    this.nodes.set(node.id, rendered)
    return rendered
  }

  retainNodes(root: PvmRenderedNode): void {
    const visible: Set<number> = new Set()
    const visit = (node: PvmRenderedNode): void => {
      visible.add(node.model.id)
      node.children.forEach(visit)
    }
    visit(root)
    Array.from(this.nodes.keys()).forEach((id) => {
      if (!visible.has(id)) this.nodes.delete(id)
    })
  }
}

function writeBuffer(path: string, value: ArrayBuffer): void {
  const file = fs.openSync(
    path,
    fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC,
  )
  try {
    if (fs.writeSync(file.fd, value) !== value.byteLength) {
      throw new Error(`Short write for ${path}`)
    }
    fs.fsyncSync(file.fd)
  } finally {
    fs.closeSync(file)
  }
}

function readBuffer(path: string): ArrayBuffer {
  const size = fs.statSync(path).size
  const value = new ArrayBuffer(size)
  const file = fs.openSync(path, fs.OpenMode.READ_ONLY)
  try {
    if (fs.readSync(file.fd, value) !== size) {
      throw new Error(`Short read for ${path}`)
    }
  } finally {
    fs.closeSync(file)
  }
  return value
}

export class PvmRuntimeSession {
  private host?: PvmRuntimeHost
  private readonly config: PvmRuntimeSessionConfig

  constructor(config: PvmRuntimeSessionConfig) {
    this.config = config
  }

  start(replace: Replace, uiContext: UIContext): void {
    if (this.host !== undefined) {
      throw new Error('PVM Runtime session is already open')
    }
    const registry = new CapabilityRegistry()
    installBasicHarmonyCapabilities(
      registry,
      this.config.context,
      uiContext,
      this.config.preferenceName,
    )
    const factory = new HarmonyNodeFactory()
    const renderer = new ArkUiRenderer(new CallbackViewHost(replace, factory), factory)
    const host = new PvmRuntimeHost(
      this.config.modulePath,
      this.config.publicKeyPath,
      this.config.applicationId,
      this.config.minimumRelease,
      this.config.channel,
      this.config.profile,
      renderer,
      registry,
      new HarmonyEd25519Verifier(),
    )
    try {
      if (fs.accessSync(this.config.statePath)) {
        try {
          host.restore(readBuffer(this.config.statePath))
        } catch (_) {
          fs.unlinkSync(this.config.statePath)
        }
      }
      host.start()
      this.host = host
    } catch (error) {
      host.close()
      throw new Error(`${error}`)
    }
  }

  persist(): void {
    if (this.host === undefined) return
    const temporary = `${this.config.statePath}.tmp`
    writeBuffer(temporary, this.host.snapshot())
    fs.moveFileSync(temporary, this.config.statePath, 0)
  }

  close(): void {
    if (this.host === undefined) return
    const host = this.host
    try {
      this.persist()
    } finally {
      host.close()
      this.host = undefined
    }
  }
}
