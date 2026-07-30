export interface ModuleResponse {
  status: number
  url: string
  headers: Record<string, string>
  body: ArrayBuffer
}

export interface ModuleTransport {
  get(url: string, headers: Record<string, string>, maximumBytes: number): Promise<ModuleResponse>
}

export interface ModuleFiles {
  exists(path: string): boolean
  readText(path: string): string
  writeTextAtomic(path: string, value: string): void
  writeBytesAtomic(path: string, value: ArrayBuffer): void
  moveAtomic(source: string, destination: string): void
  remove(path: string): void
  protectAtRest(path: string): void
  sha256(value: ArrayBuffer): string
  sha256File(path: string): string
  decodeBase64(value: string): ArrayBuffer
  decodeUtf8(value: ArrayBuffer): string
}

export interface ModuleValidator {
  validate(path: string, minimumRelease: number): number
}

export interface ModuleSignatureVerifier {
  verify(payload: ArrayBuffer, signature: ArrayBuffer, publicKeyPath: string): boolean
}

interface SignedEnvelope {
  envelope_format: number
  payload: string
  signature: string
  signature_algorithm: string
}

interface Manifest {
  application_id: string
  channel: string
  profile: string
  platform: string
  release: number
  sha256: string
  size: number
  module_url: string
}

interface State {
  format: number
  application_id: string
  channel: string
  platform: string
  profile: string
  etag: string
  release: number
  sha256: string
  history: string[]
}

export class PvmModuleStore {
  private root: string
  private server: string
  private applicationId: string
  private channel: string
  private profile: string
  private transport: ModuleTransport
  private files: ModuleFiles
  private validator: ModuleValidator
  private publicKeyPath: string
  private signatureVerifier: ModuleSignatureVerifier
  private activationToken: string
  private installationId: string
  private minimumRelease: number

  constructor(
    root: string,
    server: string,
    applicationId: string,
    channel: string,
    profile: string,
    transport: ModuleTransport,
    files: ModuleFiles,
    validator: ModuleValidator,
    publicKeyPath: string,
    signatureVerifier: ModuleSignatureVerifier,
    activationToken: string = '',
    installationId: string = '',
    minimumRelease: number = 0,
  ) {
    this.root = root
    this.server = server.replace(/\/+$/, '')
    this.applicationId = applicationId
    this.channel = channel
    this.profile = profile
    this.transport = transport
    this.files = files
    this.validator = validator
    this.publicKeyPath = publicKeyPath
    this.signatureVerifier = signatureVerifier
    this.activationToken = activationToken
    this.installationId = installationId
    this.minimumRelease = minimumRelease
    if (!server.startsWith('https://')) throw new Error('Module service must use HTTPS')
    if (!PvmModuleStore.segment(applicationId) || !PvmModuleStore.segment(channel)) {
      throw new Error('Invalid module store binding')
    }
    if (!Number.isSafeInteger(minimumRelease) || minimumRelease < 0) {
      throw new Error('Minimum release must be a non-negative safe integer')
    }
    if (!PvmModuleStore.profiles.has(profile)) throw new Error('Invalid delivery profile')
  }

  lastKnownGood(): string | undefined {
    const state = this.readState()
    if (state === undefined) return undefined
    if (state.release < this.minimumRelease) return undefined
    const path = this.modulePath(state.sha256)
    if (!this.files.exists(path) || this.files.sha256File(path) !== state.sha256) return undefined
    this.files.protectAtRest(path)
    return path
  }

  async refresh(): Promise<string> {
    try {
      return await this.refreshStrict()
    } catch (error) {
      const cached = this.lastKnownGood()
      if (cached !== undefined) return cached
      throw new Error(`${error}`)
    }
  }

  private async refreshStrict(): Promise<string> {
    const previous = this.readState()
    const cached = this.lastKnownGood()
    const headers: Record<string, string> = {}
    if (this.activationToken.length > 0) headers['Authorization'] = `Bearer ${this.activationToken}`
    if (this.installationId.length > 0) {
      headers['X-PVM-Installation-ID'] = this.installationId
    }
    if (
      previous !== undefined &&
      cached !== undefined &&
      previous.release >= this.minimumRelease &&
      previous.etag.length > 0
    ) {
      headers['If-None-Match'] = previous.etag
    }
    const url =
      `${this.server}/v1/apps/${this.applicationId}/${this.channel}/harmonyos/${this.profile}/manifest`
    const response = await this.transport.get(url, headers, 64 * 1024)
    if (response.url !== url || response.body.byteLength > 64 * 1024) {
      throw new Error('Manifest redirect or size limit violation')
    }
    if (response.status === 304) {
      const cached = this.lastKnownGood()
      if (cached === undefined) throw new Error('304 without last-known-good module')
      return cached
    }
    if (response.status !== 200) throw new Error(`Manifest request failed: ${response.status}`)
    const envelope = JSON.parse(this.files.decodeUtf8(response.body)) as SignedEnvelope
    if (
      envelope.envelope_format !== 1 ||
      envelope.signature_algorithm !== 'Ed25519' ||
      typeof envelope.payload !== 'string' ||
      typeof envelope.signature !== 'string'
    ) {
      throw new Error('Invalid signed manifest envelope')
    }
    const payload = this.files.decodeBase64(envelope.payload)
    const signature = this.files.decodeBase64(envelope.signature)
    if (
      signature.byteLength !== 64 ||
      !this.signatureVerifier.verify(payload, signature, this.publicKeyPath)
    ) {
      throw new Error('Manifest signature verification failed')
    }
    const manifest = JSON.parse(this.files.decodeUtf8(payload)) as Manifest
    const releaseFloor = Math.max(previous?.release ?? 0, this.minimumRelease)
    if (
      manifest.application_id !== this.applicationId ||
      manifest.channel !== this.channel ||
      manifest.profile !== this.profile ||
      manifest.platform !== 'harmonyos' ||
      !Number.isSafeInteger(manifest.release) ||
      manifest.release < releaseFloor ||
      !/^[0-9a-f]{64}$/.test(manifest.sha256) ||
      manifest.size < 1 ||
      manifest.size > 16 * 1024 * 1024 ||
      manifest.module_url !== `/v1/modules/${manifest.sha256}.pvm`
    ) {
      throw new Error('Invalid module manifest')
    }
    const destination = this.modulePath(manifest.sha256)
    if (this.files.exists(destination) && this.files.sha256File(destination) !== manifest.sha256) {
      this.files.remove(destination)
    }
    if (!this.files.exists(destination)) {
      const moduleUrl = `${this.server}${manifest.module_url}`
      const module = await this.transport.get(moduleUrl, headers, manifest.size)
      if (
        module.status !== 200 ||
        module.url !== moduleUrl ||
        module.body.byteLength !== manifest.size ||
        this.files.sha256(module.body) !== manifest.sha256
      ) {
        throw new Error('Module size or SHA-256 mismatch')
      }
      const temporary = `${destination}.tmp`
      try {
        this.files.writeBytesAtomic(temporary, module.body)
        const release = this.validator.validate(temporary, releaseFloor)
        if (release !== manifest.release) throw new Error('Manifest/module release mismatch')
        this.files.moveAtomic(temporary, destination)
        this.files.protectAtRest(destination)
      } finally {
        this.files.remove(temporary)
      }
    } else {
      const release = this.validator.validate(destination, releaseFloor)
      if (release !== manifest.release) throw new Error('Cached manifest/module release mismatch')
    }
    const history = [manifest.sha256]
    if (previous !== undefined && previous.sha256 !== manifest.sha256) history.push(previous.sha256)
    this.files.writeTextAtomic(
      `${this.root}/current.json`,
      JSON.stringify({
        format: 1,
        application_id: this.applicationId,
        channel: this.channel,
        platform: 'harmonyos',
        profile: this.profile,
        etag: response.headers['etag'] ?? '',
        release: manifest.release,
        sha256: manifest.sha256,
        history: history.slice(0, 2),
      }),
    )
    this.files.protectAtRest(`${this.root}/current.json`)
    return destination
  }

  private readState(): State | undefined {
    try {
      const encoded = this.files.readText(`${this.root}/current.json`)
      if (encoded.length < 1 || encoded.length > 16 * 1024) return undefined
      const state = JSON.parse(encoded) as State
      if (
        state.format !== 1 ||
        state.application_id !== this.applicationId ||
        state.channel !== this.channel ||
        state.platform !== 'harmonyos' ||
        state.profile !== this.profile ||
        typeof state.etag !== 'string' ||
        !Number.isSafeInteger(state.release) ||
        state.release < 1 ||
        !/^[0-9a-f]{64}$/.test(state.sha256) ||
        !Array.isArray(state.history) ||
        state.history.length < 1 ||
        state.history.length > 2 ||
        state.history[0] !== state.sha256 ||
        new Set(state.history).size !== state.history.length ||
        !state.history.every((value) => /^[0-9a-f]{64}$/.test(value))
      ) {
        return undefined
      }
      return state
    } catch (_) {
      return undefined
    }
  }

  private modulePath(hash: string): string {
    return `${this.root}/modules/${hash}.pvm`
  }

  private static segment(value: string): boolean {
    return /^[A-Za-z0-9._-]{1,255}$/.test(value) && value !== '.' && value !== '..'
  }

  private static profiles: Set<string> = new Set([
    'offline_sealed',
    'online_provisioned',
    'store_on_demand',
    'enterprise_managed',
  ])
}
