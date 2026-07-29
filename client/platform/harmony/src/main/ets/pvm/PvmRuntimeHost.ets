import pvm from 'libpvm_harmony.so'

export interface RuntimePolicy {
  applicationId: string
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

type SyncHandler = (operation: string, argumentsValue: object[]) => string
type AsyncHandler = (operation: string, argumentsValue: object[]) => Promise<string>

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
    return handler(operation, JSON.parse(argumentsJson) as object[])
  }

  async invokeAsync(id: string, operation: string, argumentsJson: string): Promise<string> {
    try {
      this.requireDeclared(id)
      const handler = this.async.get(id)
      if (handler === undefined) throw new Error(`Missing capability ${id}`)
      return await handler(operation, JSON.parse(argumentsJson) as object[])
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

  constructor(
    modulePath: string,
    publicKeyPath: string,
    applicationId: string,
    minimumRelease: number,
    private renderer: UiRenderer,
    private capabilities: CapabilityRegistry,
    private signatureVerifier: SignatureVerifier,
  ) {
    this.handle = pvm.create(modulePath, publicKeyPath, applicationId, minimumRelease, {
      onUi: (json: string): void => {
        const batch = JSON.parse(json) as UiBatch
        if (batch.operation !== 'replace') throw new Error('Unsupported UI batch')
        this.renderer.replaceTree(
          batch.root,
          (node, event, value) => this.dispatch(node, event, value),
        )
      },
      onSyncEffect: (capability: string, operation: string, args: string): string =>
        this.capabilities.invokeSync(capability, operation, args),
      onAsyncEffect: (taskId: string, capability: string, operation: string, args: string): void => {
        this.capabilities.invokeAsync(capability, operation, args).then((result) => {
          pvm.complete(this.handle, taskId, result)
        })
      },
      onVerifySignature: (
        payload: ArrayBuffer,
        signature: ArrayBuffer,
        keyPath: string,
      ): boolean => this.signatureVerifier.verify(payload, signature, keyPath),
    })
    this.policy = JSON.parse(pvm.metadata(this.handle)) as RuntimePolicy
    if (this.policy.platform !== 'harmonyos') {
      throw new Error(`Harmony host rejected module for platform ${this.policy.platform}`)
    }
    this.capabilities.applyPolicy(this.policy)
  }

  start(): void {
    pvm.start(this.handle)
  }

  dispatch(nodeId: number, event: string, value?: string): void {
    const code: Record<string, number> = { tap: 1, change: 2, submit: 3, appear: 4 }
    const eventCode = code[event]
    if (eventCode === undefined) throw new Error(`Unknown VM event ${event}`)
    if (value === undefined) {
      pvm.dispatch(this.handle, nodeId, eventCode)
    } else {
      pvm.dispatchValue(this.handle, nodeId, eventCode, value)
    }
  }

  snapshot(): ArrayBuffer {
    return pvm.snapshot(this.handle)
  }

  restore(state: ArrayBuffer): void {
    pvm.restore(this.handle, state)
  }

  cancelTasks(): void {
    pvm.cancel(this.handle)
  }

  close(): void {
    pvm.destroy(this.handle)
  }
}
