export interface NativeCallbacks {
  onUi(json: string): void
  onSyncEffect(capability: string, operation: string, argumentsJson: string): string | undefined
  onAsyncEffect(
    taskId: string,
    capability: string,
    operation: string,
    argumentsJson: string,
  ): void
  onVerifySignature(payload: ArrayBuffer, signature: ArrayBuffer, publicKeyPath: string): boolean
}

export const create: (
  modulePath: string,
  publicKeyPath: string,
  applicationId: string,
  minimumRelease: number,
  callbacks: NativeCallbacks,
) => object
export const start: (handle: object) => void
export const dispatch: (handle: object, nodeId: number, event: number) => void
export const dispatchValue: (
  handle: object,
  nodeId: number,
  event: number,
  value: string,
) => void
export const complete: (handle: object, taskId: string, result: string) => void
export const cancel: (handle: object) => void
export const metadata: (handle: object) => string
export const snapshot: (handle: object) => ArrayBuffer
export const restore: (handle: object, state: ArrayBuffer) => void
export const destroy: (handle: object) => void
