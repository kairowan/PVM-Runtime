import Foundation
internal import PVMBridge

@MainActor
public final class PVMHost {
    public typealias EventSink = @MainActor (UInt32, String, String?) -> Void
    public typealias RenderHandler = @MainActor (String, @escaping EventSink) throws -> Void
    public typealias ErrorHandler = @MainActor (Error) -> Void

    public let policy: PVMRuntimePolicy

    private let bridge: PVMRuntimeBridge
    private let callbacks: PVMHostCallbacks
    private let capabilities: PVMCapabilityRegistry
    private let render: RenderHandler
    private let errors: ErrorHandler
    private var closed = false

    public nonisolated static func validateModule(
        module: URL,
        publicKey: URL,
        applicationID: String,
        channel: String,
        profile: String,
        minimumRelease: UInt64
    ) throws -> UInt64 {
        var validationError: NSError?
        let release = PVMRuntimeBridge.validateModulePath(
            module.path,
            publicKeyPath: publicKey.path,
            applicationID: applicationID,
            expectedChannel: channel,
            expectedProfile: profile,
            minimumRelease: minimumRelease,
            signatureVerifier: { payload, signature, path in
                PVMPlatformCrypto.verify(
                    payload: payload,
                    signature: signature,
                    publicKeyPath: path
                )
            },
            error: &validationError
        )
        guard release > 0 else {
            throw validationError ?? PVMHostError("Runtime module validation failed")
        }
        return release
    }

    public init(
        module: URL,
        publicKey: URL,
        applicationID: String,
        channel: String,
        profile: String,
        minimumRelease: UInt64,
        capabilities: PVMCapabilityRegistry,
        render: @escaping RenderHandler,
        errors: @escaping ErrorHandler = { _ in }
    ) throws {
        let callbacks = PVMHostCallbacks()
        let bridge = try PVMRuntimeBridge(
            modulePath: module.path,
            publicKeyPath: publicKey.path,
            applicationID: applicationID,
            expectedChannel: channel,
            expectedProfile: profile,
            minimumRelease: minimumRelease,
            signatureVerifier: { payload, signature, path in
                PVMPlatformCrypto.verify(
                    payload: payload,
                    signature: signature,
                    publicKeyPath: path
                )
            },
            uiHandler: { json in callbacks.host?.apply(json) },
            syncEffectHandler: { capability, operation, arguments in
                callbacks.host?.invokeSync(
                    capability,
                    operation: operation,
                    argumentsJSON: arguments
                )
            },
            asyncEffectHandler: { _, capability, operation, arguments, complete in
                callbacks.host?.invokeAsync(
                    capability,
                    operation: operation,
                    argumentsJSON: arguments,
                    complete: complete
                )
            }
        )
        let policy = try PVMRuntimePolicy.parse(bridge.metadataJSON)
        guard policy.applicationId == applicationID,
              policy.channel == channel,
              policy.platform == "ios",
              policy.profile == profile
        else { throw PVMHostError("Runtime metadata binding mismatch") }
        try capabilities.apply(policy)

        self.bridge = bridge
        self.callbacks = callbacks
        self.capabilities = capabilities
        self.render = render
        self.errors = errors
        self.policy = policy
        callbacks.host = self
    }

    public convenience init(
        module: URL,
        publicKey: URL,
        applicationID: String,
        channel: String,
        profile: String,
        minimumRelease: UInt64,
        capabilities: PVMCapabilityRegistry,
        renderer: PVMUIKitRenderer,
        errors: @escaping ErrorHandler = { _ in }
    ) throws {
        try self.init(
            module: module,
            publicKey: publicKey,
            applicationID: applicationID,
            channel: channel,
            profile: profile,
            minimumRelease: minimumRelease,
            capabilities: capabilities,
            render: { batchJSON, events in
                renderer.enqueue(batchJSON: batchJSON, events: events, errors: errors)
            },
            errors: errors
        )
    }

    public convenience init(
        module: URL,
        publicKey: URL,
        applicationID: String,
        channel: String,
        profile: String,
        minimumRelease: UInt64,
        capabilities: PVMCapabilityRegistry,
        tree: PVMSwiftUITree,
        errors: @escaping ErrorHandler = { _ in }
    ) throws {
        try self.init(
            module: module,
            publicKey: publicKey,
            applicationID: applicationID,
            channel: channel,
            profile: profile,
            minimumRelease: minimumRelease,
            capabilities: capabilities,
            render: { batchJSON, events in
                tree.enqueue(batchJSON: batchJSON, events: events, errors: errors)
            },
            errors: errors
        )
    }

    public func start() throws {
        try requireOpen()
        try bridge.start()
    }

    public func dispatch(nodeID: UInt32, event: String, value: String? = nil) throws {
        try requireOpen()
        guard let eventCode = Self.eventCodes[event] else {
            throw PVMHostError("Unknown VM event \(event)")
        }
        try bridge.dispatchNode(nodeID, event: eventCode, value: value)
    }

    public func snapshotState() throws -> Data {
        try requireOpen()
        return try bridge.snapshotState()
    }

    public func restoreState(_ state: Data) throws {
        try requireOpen()
        try bridge.restoreState(state)
    }

    public func cancelTasks() {
        guard !closed else { return }
        bridge.cancelAllTasks()
    }

    public func close() {
        guard !closed else { return }
        closed = true
        bridge.close()
        callbacks.host = nil
    }

    private func apply(_ json: String) {
        do {
            try render(json) { [weak self] nodeID, event, value in
                do {
                    try self?.dispatch(nodeID: nodeID, event: event, value: value)
                } catch {
                    self?.errors(error)
                }
            }
        } catch {
            errors(error)
        }
    }

    private func invokeSync(
        _ capability: String,
        operation: String,
        argumentsJSON: String
    ) -> String? {
        capabilities.invokeSync(
            capability,
            operation: operation,
            argumentsJSON: argumentsJSON
        )
    }

    private func invokeAsync(
        _ capability: String,
        operation: String,
        argumentsJSON: String,
        complete: @escaping PVMCapabilityRegistry.Completion
    ) {
        capabilities.invokeAsync(
            capability,
            operation: operation,
            argumentsJSON: argumentsJSON,
            complete: complete
        )
    }

    private func requireOpen() throws {
        if closed { throw PVMHostError("Runtime is closed") }
    }

    private static let eventCodes: [String: UInt8] = [
        "tap": 1,
        "change": 2,
        "submit": 3,
        "appear": 4,
    ]
}

@MainActor
private final class PVMHostCallbacks {
    weak var host: PVMHost?
}
