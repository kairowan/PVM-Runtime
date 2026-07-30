import pvm from 'libpvm_harmony.so'

export interface RuntimePolicy {
  applicationId: string
  channel: string
  release: number
  profile: string
  platform: string
  capabilities: string[]
  capabilityVersions: Record<string, number>
  networkDomains: string[]
  storageScopes: string[]
}

export interface UiNode {
  type: string
  id: number
  props: Record<string, string>
  events: string[]
  children: UiNode[]
}

export interface UiBatch {
  operation: string
  root: UiNode
}

export interface UiRenderer {
  replaceTree(
    root: UiNode,
    emit: (nodeId: number, event: string, value?: string) => void,
  ): void
}

export interface SignatureVerifier {
  verify(payload: ArrayBuffer, signature: ArrayBuffer, publicKeyPath: string): boolean
}

interface NativeCallbacks {
  onUi(json: string): void
  onSyncEffect(capability: string, operation: string, argumentsJson: string): string
  onAsyncEffect(
    taskId: string,
    capability: string,
    operation: string,
    argumentsJson: string,
  ): void
  onVerifySignature(payload: ArrayBuffer, signature: ArrayBuffer, publicKeyPath: string): boolean
}

class NativeCallbackAdapter implements NativeCallbacks {
  private host?: PvmRuntimeHost
  private renderer: UiRenderer
  private capabilities: CapabilityRegistry
  private signatureVerifier: SignatureVerifier

  constructor(
    renderer: UiRenderer,
    capabilities: CapabilityRegistry,
    signatureVerifier: SignatureVerifier,
  ) {
    this.renderer = renderer
    this.capabilities = capabilities
    this.signatureVerifier = signatureVerifier
  }

  attach(host: PvmRuntimeHost): void {
    this.host = host
  }

  onUi(json: string): void {
    const host = this.requireHost()
    const batch = JSON.parse(json) as UiBatch
    if (batch.operation !== 'replace') throw new Error('Unsupported UI batch')
    this.renderer.replaceTree(
      batch.root,
      (node, event, value) => host.dispatch(node, event, value),
    )
  }

  onSyncEffect(capability: string, operation: string, argumentsJson: string): string {
    return this.capabilities.invokeSync(capability, operation, argumentsJson)
  }

  onAsyncEffect(
    taskId: string,
    capability: string,
    operation: string,
    argumentsJson: string,
  ): void {
    this.requireHost().completeAsync(taskId, capability, operation, argumentsJson)
  }

  onVerifySignature(
    payload: ArrayBuffer,
    signature: ArrayBuffer,
    publicKeyPath: string,
  ): boolean {
    return this.signatureVerifier.verify(payload, signature, publicKeyPath)
  }

  private requireHost(): PvmRuntimeHost {
    if (this.host === undefined) throw new Error('PVM Runtime host is not ready')
    return this.host
  }
}

export type CapabilityArgument = string | number | boolean
type SyncHandler = (operation: string, argumentsValue: CapabilityArgument[]) => string
type AsyncHandler = (operation: string, argumentsValue: CapabilityArgument[]) => Promise<string>

export class CapabilityRegistry {
  private sync: Map<string, SyncHandler> = new Map()
  private async: Map<string, AsyncHandler> = new Map()
  private versions: Map<string, number> = new Map()
  policy?: RuntimePolicy

  applyPolicy(policy: RuntimePolicy): void {
    Object.keys(policy.capabilityVersions).forEach((id) => {
      const required = policy.capabilityVersions[id]
      const installed = this.versions.get(id) ?? 0
      if (installed < required) {
        throw new Error(`Capability ${id} requires version ${required}; installed ${installed}`)
      }
    })
    this.policy = policy
  }

  registerSync(id: string, handler: SyncHandler, version: number = 1): void {
    this.registerVersion(id, version)
    if (this.sync.has(id)) throw new Error(`Duplicate capability ${id}`)
    this.sync.set(id, handler)
  }

  registerAsync(id: string, handler: AsyncHandler, version: number = 1): void {
    this.registerVersion(id, version)
    if (this.async.has(id)) throw new Error(`Duplicate capability ${id}`)
    this.async.set(id, handler)
  }

  invokeSync(id: string, operation: string, argumentsJson: string): string {
    this.requireDeclared(id)
    const handler = this.sync.get(id)
    if (handler === undefined) throw new Error(`Missing capability ${id}`)
    return handler(operation, JSON.parse(argumentsJson) as CapabilityArgument[])
  }

  async invokeAsync(id: string, operation: string, argumentsJson: string): Promise<string> {
    try {
      this.requireDeclared(id)
      const handler = this.async.get(id)
      if (handler === undefined) throw new Error(`Missing capability ${id}`)
      return await handler(operation, JSON.parse(argumentsJson) as CapabilityArgument[])
    } catch (error) {
      return JSON.stringify({ ok: false, error: `${error}` })
    }
  }

  private requireDeclared(id: string): void {
    if (this.policy === undefined || !this.policy.capabilities.includes(id)) {
      throw new Error(`Module did not declare capability ${id}`)
    }
  }

  private registerVersion(id: string, version: number): void {
    if (version < 1) throw new Error('Capability version must be positive')
    const existing = this.versions.get(id)
    if (existing !== undefined && existing !== version) {
      throw new Error(`Capability ${id} was registered with conflicting versions`)
    }
    this.versions.set(id, version)
  }
}

export class PvmRuntimeHost {
  readonly policy: RuntimePolicy
  private handle: object
  private closed: boolean = false
  private taskGeneration: number = 0
  private capabilities: CapabilityRegistry
  private asyncFailure: string = ''

  constructor(
    modulePath: string,
    publicKeyPath: string,
    applicationId: string,
    minimumRelease: number,
    expectedChannel: string,
    expectedProfile: string,
    renderer: UiRenderer,
    capabilities: CapabilityRegistry,
    signatureVerifier: SignatureVerifier,
  ) {
    this.capabilities = capabilities
    const callbacks = new NativeCallbackAdapter(renderer, capabilities, signatureVerifier)
    this.handle = pvm.create(
      modulePath,
      publicKeyPath,
      applicationId,
      minimumRelease,
      expectedChannel,
      expectedProfile,
      callbacks,
    )
    callbacks.attach(this)
    try {
      this.policy = JSON.parse(pvm.metadata(this.handle)) as RuntimePolicy
      if (this.policy.platform !== 'harmonyos') {
        throw new Error(`Harmony host rejected module for platform ${this.policy.platform}`)
      }
      if (this.policy.profile !== expectedProfile) {
        throw new Error(`Harmony host rejected module for profile ${this.policy.profile}`)
      }
      if (this.policy.channel !== expectedChannel) {
        throw new Error(`Harmony host rejected module for channel ${this.policy.channel}`)
      }
      this.capabilities.applyPolicy(this.policy)
    } catch (error) {
      pvm.destroy(this.handle)
      this.closed = true
      throw new Error(`${error}`)
    }
  }

  start(): void {
    this.requireOpen()
    pvm.start(this.handle)
  }

  dispatch(nodeId: number, event: string, value?: string): void {
    this.requireOpen()
    let eventCode: number
    switch (event) {
      case 'tap':
        eventCode = 1
        break
      case 'change':
        eventCode = 2
        break
      case 'submit':
        eventCode = 3
        break
      case 'appear':
        eventCode = 4
        break
      default:
        throw new Error(`Unknown VM event ${event}`)
    }
    if (value === undefined) {
      pvm.dispatch(this.handle, nodeId, eventCode)
    } else {
      pvm.dispatchValue(this.handle, nodeId, eventCode, value)
    }
  }

  completeAsync(
    taskId: string,
    capability: string,
    operation: string,
    argumentsJson: string,
  ): void {
    const generation = this.taskGeneration
    this.capabilities.invokeAsync(capability, operation, argumentsJson).then((result) => {
      if (!this.closed && generation === this.taskGeneration) {
        try {
          pvm.complete(this.handle, taskId, result)
        } catch (error) {
          this.recordAsyncFailure(error)
        }
      }
    }).catch((error: object) => {
      this.recordAsyncFailure(error)
    })
  }

  snapshot(): ArrayBuffer {
    this.requireOpen()
    return pvm.snapshot(this.handle)
  }

  restore(state: ArrayBuffer): void {
    this.requireOpen()
    pvm.restore(this.handle, state)
  }

  cancelTasks(): void {
    this.requireOpen()
    this.taskGeneration += 1
    pvm.cancel(this.handle)
  }

  close(): void {
    if (this.closed) return
    this.closed = true
    this.taskGeneration += 1
    pvm.cancel(this.handle)
    pvm.destroy(this.handle)
  }

  private requireOpen(): void {
    if (this.closed) throw new Error('Runtime is closed')
    if (this.asyncFailure.length > 0) {
      throw new Error(`Runtime async completion failed: ${this.asyncFailure}`)
    }
  }

  private recordAsyncFailure(error: object): void {
    if (this.closed || this.asyncFailure.length > 0) return
    this.asyncFailure = `${error}`
    this.taskGeneration += 1
    pvm.cancel(this.handle)
  }
}
