import SwiftUI

@MainActor
public final class PVMSwiftUITree: ObservableObject {
    @Published public private(set) var root: PVMUINode?
    @Published private var values: [UInt32: String] = [:]
    public var emit: (UInt32, String, String?) -> Void = { _, _, _ in }

    public init() {}

    public func replace(
        batchJSON: String,
        events: @escaping (UInt32, String, String?) -> Void
    ) throws {
        let batch = try JSONDecoder().decode(PVMUIBatch.self, from: Data(batchJSON.utf8))
        guard batch.operation == "replace" else { throw PVMHostError("Unsupported UI batch") }
        self.emit = events
        collectValues(batch.root)
        root = batch.root
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

    @ViewBuilder
    private func node(_ value: PVMUINode) -> some View {
        renderedNode(value)
            .modifier(PVMNodeBehavior(node: value, emit: tree.emit))
    }

    @ViewBuilder
    private func renderedNode(_ value: PVMUINode) -> some View {
        switch value.type {
        case "Text":
            Text(value.props["text"] ?? "")
        case "Image":
            Image(value.props["source"] ?? "")
        case "Row":
            HStack { children(value) }
        case "Column", "List":
            VStack { children(value) }
        case "Stack":
            ZStack { children(value) }
        case "Scroll":
            ScrollView { VStack { children(value) } }
        case "Button":
            Button(value.props["text"] ?? "") { tree.emit(value.id, "tap", nil) }
        case "Input":
            TextField(value.props["text"] ?? "", text: tree.stringBinding(for: value))
                .onSubmit { tree.emit(value.id, "submit", tree.value(for: value)) }
        case "Switch":
            Toggle(value.props["text"] ?? "", isOn: tree.boolBinding(for: value))
        case "NativeSurface":
            // ponytail: projects replace this placeholder with their registered UIViewRepresentable.
            Text("NativeSurface: \(value.props["surfaceType"] ?? "")")
        default:
            EmptyView()
        }
    }

    @ViewBuilder
    private func children(_ value: PVMUINode) -> some View {
        ForEach(value.children, id: \.id) { child in
            node(child)
        }
    }
}

private struct PVMNodeBehavior: ViewModifier {
    let node: PVMUINode
    let emit: (UInt32, String, String?) -> Void

    @ViewBuilder
    func body(content: Content) -> some View {
        let enabled = node.props["enabled"].flatMap(Bool.init) ?? true
        let base = content
            .disabled(!enabled)
            .onAppear {
                if node.events.contains("appear") { emit(node.id, "appear", nil) }
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
