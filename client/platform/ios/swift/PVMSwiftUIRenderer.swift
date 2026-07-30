import Combine
import SwiftUI

@MainActor
public final class PVMSwiftUITree: ObservableObject {
    @Published public private(set) var root: PVMUINode?
    @Published private var values: [UInt32: String] = [:]
    public var emit: (UInt32, String, String?) -> Void = { _, _, _ in }
    private var visibleNodeIDs: Set<UInt32> = []
    private var appearedNodeIDs: Set<UInt32> = []

    public init() {}

    public func replace(
        batchJSON: String,
        events: @escaping (UInt32, String, String?) -> Void
    ) throws {
        let batch = try JSONDecoder().decode(PVMUIBatch.self, from: Data(batchJSON.utf8))
        guard batch.operation == "replace" else { throw PVMHostError("Unsupported UI batch") }
        self.emit = events
        let nextVisible = collectIDs(batch.root)
        appearedNodeIDs.formIntersection(nextVisible)
        visibleNodeIDs = nextVisible
        collectValues(batch.root)
        root = batch.root
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
            renderedNode(value)
                .modifier(PVMNodeBehavior(node: value, emit: tree.emit, appear: tree.appear))
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
        case "Column", "List":
            return AnyView(VStack { children(value) })
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
