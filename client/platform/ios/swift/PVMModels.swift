import Foundation

public struct PVMRuntimePolicy: Decodable, Sendable {
    public let applicationId: String
    public let release: UInt64
    public let profile: String
    public let platform: String
    public let capabilities: Set<String>
    public let capabilityVersions: [String: UInt16]
    public let networkDomains: Set<String>
    public let storageScopes: Set<String>

    public static func parse(_ json: String) throws -> Self {
        try JSONDecoder().decode(Self.self, from: Data(json.utf8))
    }
}

public struct PVMUIBatch: Decodable, Sendable {
    public let operation: String
    public let root: PVMUINode
}

public struct PVMUINode: Decodable, Sendable {
    public let type: String
    public let id: UInt32
    public let props: [String: String]
    public let events: Set<String>
    public let children: [PVMUINode]
}
