import UIKit

@MainActor
public final class PVMUIKitRenderer {
    public typealias EventSink = @MainActor (UInt32, String, String?) -> Void
    public typealias SurfaceFactory = @MainActor (String, UInt32) -> UIView

    private weak var root: UIView?
    private let surfaceFactory: SurfaceFactory
    private var renderGeneration: UInt64 = 0
    private var visibleNodeIDs: Set<UInt32> = []
    private var appearedNodeIDs: Set<UInt32> = []

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
        renderGeneration += 1
        let generation = renderGeneration
        let nextVisible = collectIDs(batch.root)
        appearedNodeIDs.formIntersection(nextVisible)
        visibleNodeIDs = nextVisible
        let awaitingAppear = nextVisible.subtracting(appearedNodeIDs)
        let focused = firstResponder(in: root)
        let focusedID = focused?.tag
        let selection =
            (focused as? UITextField).flatMap { input -> Range<Int>? in
                guard let selected = input.selectedTextRange else { return nil }
                let start = input.offset(
                    from: input.beginningOfDocument,
                    to: selected.start
                )
                let end = input.offset(
                    from: input.beginningOfDocument,
                    to: selected.end
                )
                return start..<end
            }
        let rendered =
            create(
                batch.root,
                events: events,
                awaitingAppear: awaitingAppear,
                generation: generation
            )
        root.subviews.forEach { $0.removeFromSuperview() }
        rendered.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(rendered)
        NSLayoutConstraint.activate([
            rendered.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            rendered.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            rendered.topAnchor.constraint(equalTo: root.topAnchor),
            rendered.bottomAnchor.constraint(lessThanOrEqualTo: root.bottomAnchor),
        ])
        if let focusedID, let replacement = root.viewWithTag(focusedID) {
            replacement.becomeFirstResponder()
            if let input = replacement as? UITextField, let selection,
               let start = input.position(
                   from: input.beginningOfDocument,
                   offset: min(selection.lowerBound, input.text?.utf16.count ?? 0)
               ),
               let end = input.position(
                   from: input.beginningOfDocument,
                   offset: min(selection.upperBound, input.text?.utf16.count ?? 0)
               ) {
                input.selectedTextRange = input.textRange(from: start, to: end)
            }
        }
    }

    private func create(
        _ node: PVMUINode,
        events: @escaping EventSink,
        awaitingAppear: Set<UInt32>,
        generation: UInt64
    ) -> UIView {
        let view: UIView
        switch node.type {
        case "Text":
            view = UILabel()
        case "Image":
            view = UIImageView()
        case "Row":
            view = stack(.horizontal, node.children, events, awaitingAppear, generation)
        case "Column", "List":
            view = stack(.vertical, node.children, events, awaitingAppear, generation)
        case "Stack":
            let container = UIView()
            node.children.map {
                create(
                    $0,
                    events: events,
                    awaitingAppear: awaitingAppear,
                    generation: generation
                )
            }.forEach { child in
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
            let content = stack(
                .vertical,
                node.children,
                events,
                awaitingAppear,
                generation
            )
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
        view.tag = Int(node.id)
        apply(node.props, to: view)
        bind(
            node,
            to: view,
            events: events,
            awaitingAppear: awaitingAppear,
            generation: generation
        )
        return view
    }

    private func stack(
        _ axis: NSLayoutConstraint.Axis,
        _ children: [PVMUINode],
        _ events: @escaping EventSink,
        _ awaitingAppear: Set<UInt32>,
        _ generation: UInt64
    ) -> UIStackView {
        let view = UIStackView(
            arrangedSubviews: children.map {
                create(
                    $0,
                    events: events,
                    awaitingAppear: awaitingAppear,
                    generation: generation
                )
            }
        )
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

    private func bind(
        _ node: PVMUINode,
        to view: UIView,
        events: @escaping EventSink,
        awaitingAppear: Set<UInt32>,
        generation: UInt64
    ) {
        if node.events.contains("tap"), let control = view as? UIControl {
            control.addAction(UIAction { _ in events(node.id, "tap", nil) }, for: .touchUpInside)
        } else if node.events.contains("tap") {
            view.isUserInteractionEnabled = true
            view.addGestureRecognizer(
                PVMClosureTapGestureRecognizer {
                    events(node.id, "tap", nil)
                }
            )
        }
        if node.events.contains("change"), let control = view as? UIControl {
            control.addAction(
                UIAction { _ in events(node.id, "change", self.value(of: control)) },
                for: control is UITextField ? .editingChanged : .valueChanged
            )
        }
        if node.events.contains("submit"), let input = view as? UITextField {
            input.addAction(
                UIAction { _ in events(node.id, "submit", input.text ?? "") },
                for: .editingDidEndOnExit
            )
        }
        if node.events.contains("appear"), awaitingAppear.contains(node.id) {
            DispatchQueue.main.async { [weak self] in
                guard let self,
                      self.renderGeneration == generation,
                      self.visibleNodeIDs.contains(node.id),
                      self.appearedNodeIDs.insert(node.id).inserted
                else { return }
                events(node.id, "appear", nil)
            }
        }
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

    private func firstResponder(in view: UIView) -> UIView? {
        if view.isFirstResponder { return view }
        return view.subviews.lazy.compactMap(firstResponder).first
    }

    private func value(of control: UIControl) -> String? {
        if let input = control as? UITextField { return input.text ?? "" }
        if let toggle = control as? UISwitch { return String(toggle.isOn) }
        return nil
    }
}

private final class PVMClosureTapGestureRecognizer: UITapGestureRecognizer {
    private let handler: () -> Void

    init(handler: @escaping () -> Void) {
        self.handler = handler
        super.init(target: nil, action: nil)
        addTarget(self, action: #selector(invoke))
    }

    @objc private func invoke() {
        handler()
    }
}
