import UIKit

@MainActor
public final class PVMUIKitRenderer {
    public typealias EventSink = @MainActor (UInt32, String, String?) -> Void
    public typealias SurfaceFactory = @MainActor (String, UInt32) -> UIView

    private weak var root: UIView?
    private let surfaceFactory: SurfaceFactory

    public init(
        root: UIView,
        surfaceFactory: @escaping SurfaceFactory = { type, _ in
            let view = UIView()
            view.accessibilityLabel = "Missing native surface: \(type)"
            return view
        }
    ) {
        self.root = root
        self.surfaceFactory = surfaceFactory
    }

    public func replace(batchJSON: String, events: @escaping EventSink) throws {
        let batch = try JSONDecoder().decode(PVMUIBatch.self, from: Data(batchJSON.utf8))
        guard batch.operation == "replace", let root else {
            throw PVMHostError("Unsupported UI batch or missing root view")
        }
        let rendered = create(batch.root, events: events)
        root.subviews.forEach { $0.removeFromSuperview() }
        rendered.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(rendered)
        NSLayoutConstraint.activate([
            rendered.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            rendered.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            rendered.topAnchor.constraint(equalTo: root.topAnchor),
            rendered.bottomAnchor.constraint(lessThanOrEqualTo: root.bottomAnchor),
        ])
    }

    private func create(_ node: PVMUINode, events: @escaping EventSink) -> UIView {
        let view: UIView
        switch node.type {
        case "Text":
            view = UILabel()
        case "Image":
            view = UIImageView()
        case "Row":
            view = stack(.horizontal, node.children, events)
        case "Column", "List":
            view = stack(.vertical, node.children, events)
        case "Stack":
            let container = UIView()
            node.children.map { create($0, events: events) }.forEach { child in
                child.translatesAutoresizingMaskIntoConstraints = false
                container.addSubview(child)
                NSLayoutConstraint.activate([
                    child.leadingAnchor.constraint(equalTo: container.leadingAnchor),
                    child.trailingAnchor.constraint(equalTo: container.trailingAnchor),
                    child.topAnchor.constraint(equalTo: container.topAnchor),
                    child.bottomAnchor.constraint(equalTo: container.bottomAnchor),
                ])
            }
            view = container
        case "Scroll":
            let scroll = UIScrollView()
            let content = stack(.vertical, node.children, events)
            content.translatesAutoresizingMaskIntoConstraints = false
            scroll.addSubview(content)
            NSLayoutConstraint.activate([
                content.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor),
                content.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor),
                content.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor),
                content.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor),
                content.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor),
            ])
            view = scroll
        case "Button":
            view = UIButton(type: .system)
        case "Input":
            view = UITextField()
        case "Switch":
            view = UISwitch()
        case "NativeSurface":
            view = surfaceFactory(node.props["surfaceType"] ?? "", node.id)
        default:
            preconditionFailure("Unsupported VM node type \(node.type)")
        }
        apply(node.props, to: view)
        bind(node, to: view, events: events)
        return view
    }

    private func stack(
        _ axis: NSLayoutConstraint.Axis,
        _ children: [PVMUINode],
        _ events: @escaping EventSink
    ) -> UIStackView {
        let view = UIStackView(arrangedSubviews: children.map { create($0, events: events) })
        view.axis = axis
        view.alignment = .fill
        return view
    }

    private func apply(_ props: [String: String], to view: UIView) {
        view.accessibilityLabel = props["accessibilityLabel"]
        if let enabled = props["enabled"].flatMap(Bool.init) {
            view.isUserInteractionEnabled = enabled
            (view as? UIControl)?.isEnabled = enabled
        }
        if let text = props["text"] {
            switch view {
            case let label as UILabel: label.text = text
            case let button as UIButton: button.setTitle(text, for: .normal)
            default: break
            }
        }
        if let value = props["value"] {
            if let input = view as? UITextField { input.text = value }
            if let toggle = view as? UISwitch { toggle.isOn = Bool(value) ?? false }
        }
    }

    private func bind(_ node: PVMUINode, to view: UIView, events: @escaping EventSink) {
        if node.events.contains("tap"), let control = view as? UIControl {
            control.addAction(UIAction { _ in events(node.id, "tap", nil) }, for: .touchUpInside)
        }
        if node.events.contains("change"), let control = view as? UIControl {
            control.addAction(
                UIAction { _ in events(node.id, "change", self.value(of: control)) },
                for: .valueChanged
            )
        }
        if node.events.contains("submit"), let input = view as? UITextField {
            input.addAction(
                UIAction { _ in events(node.id, "submit", input.text ?? "") },
                for: .editingDidEndOnExit
            )
        }
        if node.events.contains("appear") {
            DispatchQueue.main.async { events(node.id, "appear", nil) }
        }
    }

    private func value(of control: UIControl) -> String? {
        if let input = control as? UITextField { return input.text ?? "" }
        if let toggle = control as? UISwitch { return String(toggle.isOn) }
        return nil
    }
}
