import Foundation

public final class PVMCapabilityRegistry: @unchecked Sendable {
    public typealias SyncHandler = (String, [Any]) throws -> String
    public typealias AsyncHandler = (String, [Any], @escaping (String) -> Void) throws -> Void

    private var sync: [String: SyncHandler] = [:]
    private var async: [String: AsyncHandler] = [:]
    private var versions: [String: UInt16] = [:]
    public private(set) var policy: PVMRuntimePolicy?

    public init() {}

    public func apply(_ policy: PVMRuntimePolicy) throws {
        for (id, required) in policy.capabilityVersions
        where versions[id, default: 0] < required {
            throw PVMHostError(
                "Capability \(id) requires version \(required); installed \(versions[id, default: 0])"
            )
        }
        self.policy = policy
    }

    public func registerSync(
        _ id: String, version: UInt16 = 1, _ handler: @escaping SyncHandler
    ) {
        registerVersion(id, version)
        precondition(sync.updateValue(handler, forKey: id) == nil, "Duplicate capability \(id)")
    }

    public func registerAsync(
        _ id: String, version: UInt16 = 1, _ handler: @escaping AsyncHandler
    ) {
        registerVersion(id, version)
        precondition(async.updateValue(handler, forKey: id) == nil, "Duplicate capability \(id)")
    }

    public func invokeSync(_ id: String, operation: String, argumentsJSON: String) -> String? {
        do {
            try requireDeclared(id)
            let arguments = try Self.arguments(argumentsJSON)
            return try sync[id].map { try $0(operation, arguments) }
        } catch {
            return nil
        }
    }

    public func invokeAsync(
        _ id: String,
        operation: String,
        argumentsJSON: String,
        complete: @escaping (String) -> Void
    ) {
        do {
            try requireDeclared(id)
            guard let handler = async[id] else { throw PVMHostError("Missing capability \(id)") }
            try handler(operation, Self.arguments(argumentsJSON), complete)
        } catch {
            let body = ["ok": false, "error": error.localizedDescription] as [String: Any]
            let data = try? JSONSerialization.data(withJSONObject: body)
            complete(data.flatMap { String(data: $0, encoding: .utf8) } ?? #"{"ok":false}"#)
        }
    }

    private func requireDeclared(_ id: String) throws {
        guard policy?.capabilities.contains(id) == true else {
            throw PVMHostError("Module did not declare capability \(id)")
        }
    }

    private func registerVersion(_ id: String, _ version: UInt16) {
        precondition(version > 0, "Capability version must be positive")
        precondition(
            versions[id] == nil || versions[id] == version,
            "Capability \(id) was registered with conflicting versions"
        )
        versions[id] = version
    }

    private static func arguments(_ json: String) throws -> [Any] {
        guard let values = try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [Any] else {
            throw PVMHostError("Capability arguments are not an array")
        }
        return values
    }
}

public struct PVMHostError: LocalizedError {
    let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}
