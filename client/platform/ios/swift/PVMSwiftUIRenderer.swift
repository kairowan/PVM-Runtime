import Combine
import SwiftUI

@MainActor
public final class PVMSwiftUITree: ObservableObject {
    @Published public private(set) var root: PVMUINode?
    @Published private var values: [UInt32: String] = [:]
    public var emit: (UInt32, String, String?) -> Void = { _, _, _ in }
    private var visibleNodeIDs: Set<UInt32> = []
    private var appearedNodeIDs: Set<UInt32> = []
    private var pendingBatch: PendingBatch?
    private var decodeTask: Task<Void, Never>?
    private var requestGeneration: UInt64 = 0
    private var pathsByID: [UInt32: [Int]] = [:]

    public init() {}

    public func replace(
        batchJSON: String,
        events: @escaping (UInt32, String, String?) -> Void
    ) throws {
        requestGeneration += 1
        pendingBatch = nil
        try apply(PVMUIBatchDecoder.decode(batchJSON), events: events)
    }

    public func enqueue(
        batchJSON: String,
        events: @escaping (UInt32, String, String?) -> Void,
        errors: @escaping @MainActor (Error) -> Void
    ) {
        requestGeneration += 1
        let generation = requestGeneration
        if batchJSON.utf8.count <= Self.backgroundDecodeThreshold,
           decodeTask == nil,
           pendingBatch == nil {
            do {
                try apply(PVMUIBatchDecoder.decode(batchJSON), events: events)
            } catch {
                errors(error)
            }
            return
        }
        pendingBatch = PendingBatch(
            generation: generation,
            json: batchJSON,
            events: events,
            errors: errors
        )
        guard decodeTask == nil else { return }
        decodeTask = Task { [weak self] in
            await self?.drainBatches()
        }
    }

    private func drainBatches() async {
        while let pending = pendingBatch {
            pendingBatch = nil
            let json = pending.json
            let decoded =
                await Task.detached(priority: .userInitiated) {
                    try PVMUIBatchDecoder.decode(json)
                }.result
            guard !Task.isCancelled, pending.generation == requestGeneration else { continue }
            switch decoded {
            case .success(let batch):
                do {
                    try apply(batch, events: pending.events)
                } catch {
                    pending.errors(error)
                }
            case .failure(let error):
                pending.errors(error)
            }
        }
        decodeTask = nil
    }

    func apply(
        _ batch: PVMUIBatch,
        events: @escaping (UInt32, String, String?) -> Void
    ) throws {
        guard batch.operation == "replace" || batch.operation == "patch" else {
            throw PVMHostError("Unsupported UI batch")
        }
        self.emit = events
        if let previous = root,
           !batch.structureChanged,
           previous.id == batch.rootID,
           previous.type == batch.rootType {
            if previous.revision == batch.rootRevision { return }
            guard !batch.changed.isEmpty else {
                throw PVMHostError("Incremental SwiftUI batch has no changed nodes")
            }
            for id in batch.changed {
                guard let node = batch.nodesByID[id] else {
                    throw PVMHostError("Changed UI node \(id) is missing")
                }
                collectValues(node)
            }
            if let completeRoot = batch.root {
                root = completeRoot
                return
            }
            var next = previous
            for id in batch.changed {
                guard let replacement = batch.nodesByID[id], let path = pathsByID[id] else {
                    throw PVMHostError("Changed UI node \(id) has no stable path")
                }
                next = try replacing(
                    next,
                    at: path[...],
                    with: replacement,
                    revisions: batch.revisions
                )
            }
            if next.revision != batch.rootRevision {
                next = copy(next, revision: batch.rootRevision, children: next.children)
            }
            root = next
            return
        }
        guard let nextRoot = batch.root else {
            throw PVMHostError("A structural PVM update requires a complete root")
        }
        let nextVisible = collectIDs(nextRoot)
        appearedNodeIDs.formIntersection(nextVisible)
        visibleNodeIDs = nextVisible
        collectValues(nextRoot)
        pathsByID = indexPaths(nextRoot)
        root = nextRoot
    }

    public func appear(_ nodeID: UInt32) {
        guard visibleNodeIDs.contains(nodeID), appearedNodeIDs.insert(nodeID).inserted else {
            return
        }
        emit(nodeID, "appear", nil)
    }

    public func stringBinding(for node: PVMUINode) -> Binding<String> {
        Binding(
            get: { self.values[node.id] ?? node.props["value"] ?? "" },
            set: {
                self.values[node.id] = $0
                self.emit(node.id, "change", $0)
            }
        )
    }

    public func boolBinding(for node: PVMUINode) -> Binding<Bool> {
        Binding(
            get: { (self.values[node.id] ?? node.props["value"]) == "true" },
            set: {
                let value = String($0)
                self.values[node.id] = value
                self.emit(node.id, "change", value)
            }
        )
    }

    public func value(for node: PVMUINode) -> String {
        values[node.id] ?? node.props["value"] ?? ""
    }

    private func collectValues(_ node: PVMUINode) {
        if node.type == "Input" || node.type == "Switch" {
            values[node.id] = node.props["value"] ?? ""
        }
        node.children.forEach(collectValues)
    }

    private func collectIDs(_ root: PVMUINode) -> Set<UInt32> {
        var result: Set<UInt32> = []
        func visit(_ node: PVMUINode) {
            result.insert(node.id)
            node.children.forEach(visit)
        }
        visit(root)
        return result
    }

    private func indexPaths(_ root: PVMUINode) -> [UInt32: [Int]] {
        var result: [UInt32: [Int]] = [:]
        func visit(_ node: PVMUINode, path: [Int]) {
            result[node.id] = path
            for (index, child) in node.children.enumerated() {
                visit(child, path: path + [index])
            }
        }
        visit(root, path: [])
        return result
    }

    private func replacing(
        _ node: PVMUINode,
        at path: ArraySlice<Int>,
        with replacement: PVMUINode,
        revisions: [UInt32: UInt64]
    ) throws -> PVMUINode {
        guard let index = path.first else { return replacement }
        guard node.children.indices.contains(index) else {
            throw PVMHostError("Incremental SwiftUI path is no longer valid")
        }
        var children = node.children
        children[index] = try replacing(
            children[index],
            at: path.dropFirst(),
            with: replacement,
            revisions: revisions
        )
        return copy(
            node,
            revision: revisions[node.id] ?? node.revision,
            children: children
        )
    }

    private func copy(
        _ node: PVMUINode,
        revision: UInt64,
        children: [PVMUINode]
    ) -> PVMUINode {
        PVMUINode(
            type: node.type,
            id: node.id,
            revision: revision,
            props: node.props,
            events: node.events,
            children: children
        )
    }

    private struct PendingBatch {
        let generation: UInt64
        let json: String
        let events: (UInt32, String, String?) -> Void
        let errors: @MainActor (Error) -> Void
    }

    private static let backgroundDecodeThreshold = 32 * 1024
}

public struct PVMSwiftUIRenderer: View {
    @ObservedObject private var tree: PVMSwiftUITree

    public init(tree: PVMSwiftUITree) {
        self.tree = tree
    }

    public var body: some View {
        Group {
            if let root = tree.root {
                node(root)
            }
        }
    }

    private func node(_ value: PVMUINode) -> AnyView {
        // ponytail: the DSL tree is dynamic; type erasure prevents recursive generic
        // expansion during Swift compilation. Replace only after renderer profiling.
        AnyView(
            PVMRevisionGate(nodeID: value.id, revision: value.revision) {
                renderedNode(value)
                    .modifier(
                        PVMNodeBehavior(node: value, emit: tree.emit, appear: tree.appear)
                    )
            }
            .equatable()
        )
    }

    private func renderedNode(_ value: PVMUINode) -> AnyView {
        switch value.type {
        case "Text":
            return AnyView(Text(value.props["text"] ?? ""))
        case "Image":
            return AnyView(Image(value.props["source"] ?? ""))
        case "Row":
            return AnyView(HStack { children(value) })
        case "Column":
            return AnyView(VStack { children(value) })
        case "List":
            return AnyView(
                List(value.children, id: \.id) { child in
                    node(child)
                }
                .listStyle(.plain)
            )
        case "Stack":
            return AnyView(ZStack { children(value) })
        case "Scroll":
            return AnyView(ScrollView { VStack { children(value) } })
        case "Button":
            return AnyView(
                Button(value.props["text"] ?? "") { tree.emit(value.id, "tap", nil) }
            )
        case "Input":
            return AnyView(
                TextField(value.props["text"] ?? "", text: tree.stringBinding(for: value))
                    .onSubmit { tree.emit(value.id, "submit", tree.value(for: value)) }
            )
        case "Switch":
            return AnyView(
                Toggle(value.props["text"] ?? "", isOn: tree.boolBinding(for: value))
            )
        case "NativeSurface":
            // ponytail: projects replace this placeholder with their registered UIViewRepresentable.
            return AnyView(Text("NativeSurface: \(value.props["surfaceType"] ?? "")"))
        default:
            return AnyView(EmptyView())
        }
    }

    private func children(_ value: PVMUINode) -> AnyView {
        AnyView(ForEach(value.children, id: \.id) { child in node(child) })
    }
}

private struct PVMRevisionGate<Content: View>: View, Equatable {
    let nodeID: UInt32
    let revision: UInt64
    let content: () -> Content

    nonisolated static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.nodeID == rhs.nodeID && lhs.revision == rhs.revision
    }

    var body: some View {
        content()
    }
}

private struct PVMNodeBehavior: ViewModifier {
    let node: PVMUINode
    let emit: (UInt32, String, String?) -> Void
    let appear: (UInt32) -> Void

    @ViewBuilder
    func body(content: Content) -> some View {
        let enabled = node.props["enabled"].flatMap(Bool.init) ?? true
        let base = content
            .disabled(!enabled)
            .onAppear {
                if node.events.contains("appear") { appear(node.id) }
            }
        if let label = node.props["accessibilityLabel"] {
            interactive(base.accessibilityLabel(Text(label)))
        } else {
            interactive(base)
        }
    }

    @ViewBuilder
    private func interactive<Content: View>(_ content: Content) -> some View {
        if node.type != "Button" && node.events.contains("tap") {
            content.onTapGesture { emit(node.id, "tap", nil) }
        } else {
            content
        }
    }
}
