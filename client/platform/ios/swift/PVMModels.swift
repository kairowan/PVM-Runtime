import Foundation

public struct PVMRuntimePolicy: Decodable, Sendable {
    public let applicationId: String
    public let channel: String
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

public struct PVMUIBatch: Decodable, Equatable, Sendable {
    public let wireVersion: UInt32
    public let operation: String
    public let structureChanged: Bool
    public let changed: [UInt32]
    public let root: PVMUINode?
    public let rootID: UInt32
    public let rootType: String
    public let rootRevision: UInt64
    public let revisions: [UInt32: UInt64]
    let nodesByID: [UInt32: PVMUINode]

    private enum CodingKeys: String, CodingKey {
        case wireVersion
        case operation
        case structureChanged
        case changed
        case root
        case rootID = "rootId"
        case rootType
        case rootRevision
        case nodes
        case revisions
    }

    private struct Revision: Decodable {
        let id: UInt32
        let revision: UInt64
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        wireVersion = try values.decodeIfPresent(UInt32.self, forKey: .wireVersion) ?? 1
        operation = try values.decode(String.self, forKey: .operation)
        guard operation == "replace" || operation == "patch" else {
            throw DecodingError.dataCorruptedError(
                forKey: .operation,
                in: values,
                debugDescription: "Unsupported UI batch"
            )
        }
        guard operation != "patch" || wireVersion == 2 else {
            throw DecodingError.dataCorruptedError(
                forKey: .wireVersion,
                in: values,
                debugDescription: "Patch requires UI wire v2"
            )
        }
        structureChanged =
            try values.decodeIfPresent(Bool.self, forKey: .structureChanged) ?? true
        guard operation != "patch" || !structureChanged else {
            throw DecodingError.dataCorruptedError(
                forKey: .structureChanged,
                in: values,
                debugDescription: "Structural UI changes require a complete root"
            )
        }
        changed = try values.decodeIfPresent([UInt32].self, forKey: .changed) ?? []
        guard Set(changed).count == changed.count else {
            throw DecodingError.dataCorruptedError(
                forKey: .changed,
                in: values,
                debugDescription: "Duplicate changed UI node id"
            )
        }
        root = try values.decodeIfPresent(PVMUINode.self, forKey: .root)
        guard operation != "replace" || root != nil else {
            throw DecodingError.dataCorruptedError(
                forKey: .root,
                in: values,
                debugDescription: "Replacement root is missing"
            )
        }
        if let root {
            rootID = root.id
            rootType = root.type
            rootRevision = root.revision
            nodesByID = try Self.index(root, key: .root, values: values)
        } else {
            rootID = try values.decode(UInt32.self, forKey: .rootID)
            rootType = try values.decode(String.self, forKey: .rootType)
            rootRevision = try values.decode(UInt64.self, forKey: .rootRevision)
            let nodes = try values.decode([PVMUINode].self, forKey: .nodes)
            guard Set(nodes.map(\.id)).count == nodes.count else {
                throw DecodingError.dataCorruptedError(
                    forKey: .nodes,
                    in: values,
                    debugDescription: "Duplicate changed UI node payload"
                )
            }
            for node in nodes {
                _ = try Self.index(node, key: .nodes, values: values)
            }
            nodesByID = Dictionary(uniqueKeysWithValues: nodes.map { ($0.id, $0) })
        }
        var revisionIndex: [UInt32: UInt64] = [:]
        for item in try values.decodeIfPresent([Revision].self, forKey: .revisions) ?? [] {
            guard revisionIndex.updateValue(item.revision, forKey: item.id) == nil else {
                throw DecodingError.dataCorruptedError(
                    forKey: .revisions,
                    in: values,
                    debugDescription: "Duplicate UI revision id \(item.id)"
                )
            }
        }
        revisions = revisionIndex
        for id in changed where nodesByID[id] == nil {
            throw DecodingError.dataCorruptedError(
                forKey: .changed,
                in: values,
                debugDescription: "Changed UI node \(id) is missing"
            )
        }
    }

    private static func index(
        _ root: PVMUINode,
        key: CodingKeys,
        values: KeyedDecodingContainer<CodingKeys>
    ) throws -> [UInt32: PVMUINode] {
        var index: [UInt32: PVMUINode] = [:]
        var pending = [root]
        while let node = pending.popLast() {
            guard index.updateValue(node, forKey: node.id) == nil else {
                throw DecodingError.dataCorruptedError(
                    forKey: key,
                    in: values,
                    debugDescription: "Duplicate UI node id \(node.id)"
                )
            }
            pending.append(contentsOf: node.children)
        }
        return index
    }
}

public struct PVMUINode: Decodable, Equatable, Sendable {
    public let type: String
    public let id: UInt32
    public let revision: UInt64
    public let props: [String: String]
    public let events: Set<String>
    public let children: [PVMUINode]

    public init(
        type: String,
        id: UInt32,
        revision: UInt64,
        props: [String: String],
        events: Set<String>,
        children: [PVMUINode]
    ) {
        self.type = type
        self.id = id
        self.revision = revision
        self.props = props
        self.events = events
        self.children = children
    }
}

enum PVMUIBatchDecoder {
    nonisolated static func decode(_ json: String) throws -> PVMUIBatch {
        try JSONDecoder().decode(PVMUIBatch.self, from: Data(json.utf8))
    }
}
