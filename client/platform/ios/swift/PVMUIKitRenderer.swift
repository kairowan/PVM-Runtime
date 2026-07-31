import UIKit

@MainActor
public final class PVMUIKitRenderer {
    public typealias EventSink = @MainActor (UInt32, String, String?) -> Void
    public typealias SurfaceFactory = @MainActor (String, UInt32) -> UIView

    private weak var root: UIView?
    private let surfaceFactory: SurfaceFactory
    private var viewsByID: [UInt32: CachedView] = [:]
    private var pendingBatch: PendingBatch?
    private var decodeTask: Task<Void, Never>?
    private var requestGeneration: UInt64 = 0
    private var renderGeneration: UInt64 = 0
    private var visibleNodeIDs: Set<UInt32> = []
    private var appearedNodeIDs: Set<UInt32> = []
    private var renderedTree: PVMUINode?
    private var renderedRootID: UInt32?
    private var renderedRootType: String?
    private var renderedRootRevision: UInt64?

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
        requestGeneration += 1
        pendingBatch = nil
        try apply(PVMUIBatchDecoder.decode(batchJSON), events: events)
    }

    public func enqueue(
        batchJSON: String,
        events: @escaping EventSink,
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

    func apply(_ batch: PVMUIBatch, events: @escaping EventSink) throws {
        guard (batch.operation == "replace" || batch.operation == "patch"), let root else {
            throw PVMHostError("Unsupported UI batch or missing root view")
        }
        if renderedTree != nil,
           !batch.structureChanged,
           renderedRootID == batch.rootID,
           renderedRootType == batch.rootType {
            if renderedRootRevision == batch.rootRevision { return }
            renderGeneration += 1
            let generation = renderGeneration
            let awaitingAppear = visibleNodeIDs.subtracting(appearedNodeIDs)
            for id in batch.changed {
                guard let node = batch.nodesByID[id] else {
                    throw PVMHostError("Changed UI node \(id) is missing")
                }
                try applyChangedNode(
                    node,
                    events: events,
                    awaitingAppear: awaitingAppear,
                    generation: generation
                )
            }
            renderedRootRevision = batch.rootRevision
            return
        }
        guard let nextRoot = batch.root else {
            throw PVMHostError("A structural PVM update requires a complete root")
        }
        renderGeneration += 1
        let generation = renderGeneration
        let nextVisible = collectIDs(nextRoot)
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
            reconcile(
                nextRoot,
                events: events,
                awaitingAppear: awaitingAppear,
                generation: generation
            )
        viewsByID = viewsByID.filter { nextVisible.contains($0.key) }
        if root.subviews.count != 1 || root.subviews[0] !== rendered {
            detach(rendered)
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
        renderedTree = nextRoot
        renderedRootID = nextRoot.id
        renderedRootType = nextRoot.type
        renderedRootRevision = nextRoot.revision
    }

    private func applyChangedNode(
        _ node: PVMUINode,
        events: @escaping EventSink,
        awaitingAppear: Set<UInt32>,
        generation: UInt64
    ) throws {
        guard let cached = viewsByID[node.id], let view = cached.view else {
            throw PVMHostError("Changed PVM node \(node.id) lost its native view")
        }
        guard cached.key == cacheKey(for: node) else {
            throw PVMHostError(
                "Changed PVM node \(node.id) requires structural reconciliation"
            )
        }
        let selection =
            (view as? UITextField).flatMap { input -> Range<Int>? in
                guard input.isFirstResponder, let selected = input.selectedTextRange else {
                    return nil
                }
                return input.offset(
                    from: input.beginningOfDocument,
                    to: selected.start
                )..<input.offset(
                    from: input.beginningOfDocument,
                    to: selected.end
                )
            }
        prepareForReuse(view)
        apply(node.props, to: view)
        if node.type == "List" {
            (view as! PVMCollectionListView).replace(nodes: node.children) { [weak self] child in
                guard let self else { return UIView() }
                return self.reconcile(
                    child,
                    events: events,
                    awaitingAppear: awaitingAppear,
                    generation: generation
                )
            }
        }
        bind(
            node,
            to: view,
            events: events,
            awaitingAppear: awaitingAppear,
            generation: generation
        )
        if let input = view as? UITextField, let selection,
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
        viewsByID[node.id] = CachedView(
            key: cached.key,
            revision: node.revision,
            view: view
        )
    }

    private func reconcile(
        _ node: PVMUINode,
        events: @escaping EventSink,
        awaitingAppear: Set<UInt32>,
        generation: UInt64
    ) -> UIView {
        let key = cacheKey(for: node)
        let view: UIView
        if let cached = viewsByID[node.id],
           cached.key == key,
           cached.revision == node.revision,
           let cachedView = cached.view {
            return cachedView
        } else if let cached = viewsByID[node.id],
                  cached.key == key,
                  let cachedView = cached.view {
            view = cachedView
        } else {
            view = createShell(node)
        }
        view.tag = Int(node.id)
        prepareForReuse(view)
        apply(node.props, to: view)
        switch node.type {
        case "Row", "Column":
            reconcileArrangedChildren(
                view as! UIStackView,
                nodes: node.children,
                events: events,
                awaitingAppear: awaitingAppear,
                generation: generation
            )
        case "List":
            (view as! PVMCollectionListView).replace(nodes: node.children) { [weak self] child in
                guard let self else { return UIView() }
                return self.reconcile(
                    child,
                    events: events,
                    awaitingAppear: awaitingAppear,
                    generation: generation
                )
            }
        case "Stack":
            reconcileOverlayChildren(
                view,
                nodes: node.children,
                events: events,
                awaitingAppear: awaitingAppear,
                generation: generation
            )
        case "Scroll":
            reconcileArrangedChildren(
                (view as! UIScrollView).subviews[0] as! UIStackView,
                nodes: node.children,
                events: events,
                awaitingAppear: awaitingAppear,
                generation: generation
            )
        default:
            break
        }
        bind(
            node,
            to: view,
            events: events,
            awaitingAppear: awaitingAppear,
            generation: generation
        )
        viewsByID[node.id] = CachedView(
            key: key,
            revision: node.revision,
            view: view
        )
        return view
    }

    private func createShell(_ node: PVMUINode) -> UIView {
        let view: UIView
        switch node.type {
        case "Text":
            let label = UILabel()
            label.font = .preferredFont(forTextStyle: .title3)
            label.adjustsFontForContentSizeCategory = true
            label.numberOfLines = 0
            view = label
        case "Image":
            view = UIImageView()
        case "Row":
            view = stack(.horizontal)
        case "Column":
            view = stack(.vertical)
        case "List":
            view = PVMCollectionListView()
        case "Stack":
            view = UIView()
        case "Scroll":
            let scroll = UIScrollView()
            let content = stack(.vertical)
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
            let button = UIButton(type: .system)
            button.configuration = .gray()
            button.heightAnchor.constraint(greaterThanOrEqualToConstant: 50).isActive = true
            view = button
        case "Input":
            let input = UITextField()
            input.borderStyle = .roundedRect
            input.clearButtonMode = .whileEditing
            input.heightAnchor.constraint(greaterThanOrEqualToConstant: 44).isActive = true
            view = input
        case "Switch":
            view = UISwitch()
        case "NativeSurface":
            view = surfaceFactory(node.props["surfaceType"] ?? "", node.id)
        default:
            preconditionFailure("Unsupported VM node type \(node.type)")
        }
        return view
    }

    private func stack(_ axis: NSLayoutConstraint.Axis) -> UIStackView {
        let view = UIStackView()
        view.axis = axis
        view.alignment = .fill
        view.spacing = 12
        return view
    }

    private func reconcileArrangedChildren(
        _ stack: UIStackView,
        nodes: [PVMUINode],
        events: @escaping EventSink,
        awaitingAppear: Set<UInt32>,
        generation: UInt64
    ) {
        let desired = nodes.map {
            reconcile(
                $0,
                events: events,
                awaitingAppear: awaitingAppear,
                generation: generation
            )
        }
        stack.arrangedSubviews.filter { !desired.contains($0) }.forEach {
            stack.removeArrangedSubview($0)
            $0.removeFromSuperview()
        }
        for (index, child) in desired.enumerated() {
            if stack.arrangedSubviews.indices.contains(index),
               stack.arrangedSubviews[index] === child {
                continue
            }
            detach(child)
            stack.insertArrangedSubview(child, at: index)
        }
    }

    private func reconcileOverlayChildren(
        _ container: UIView,
        nodes: [PVMUINode],
        events: @escaping EventSink,
        awaitingAppear: Set<UInt32>,
        generation: UInt64
    ) {
        let desired = nodes.map {
            reconcile(
                $0,
                events: events,
                awaitingAppear: awaitingAppear,
                generation: generation
            )
        }
        container.subviews.filter { !desired.contains($0) }.forEach { $0.removeFromSuperview() }
        NSLayoutConstraint.deactivate(container.constraints)
        for (index, child) in desired.enumerated() {
            if child.superview !== container {
                detach(child)
                container.insertSubview(child, at: index)
            } else {
                container.insertSubview(child, at: index)
            }
            child.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([
                child.leadingAnchor.constraint(equalTo: container.leadingAnchor),
                child.trailingAnchor.constraint(equalTo: container.trailingAnchor),
                child.topAnchor.constraint(equalTo: container.topAnchor),
                child.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            ])
        }
    }

    private func detach(_ view: UIView) {
        (view.superview as? UIStackView)?.removeArrangedSubview(view)
        view.removeFromSuperview()
    }

    private func prepareForReuse(_ view: UIView) {
        view.gestureRecognizers?
            .filter { $0 is PVMClosureTapGestureRecognizer }
            .forEach(view.removeGestureRecognizer)
        guard let control = view as? UIControl else { return }
        control.removeAction(identifiedBy: Self.tapActionID, for: .touchUpInside)
        control.removeAction(identifiedBy: Self.changeActionID, for: .editingChanged)
        control.removeAction(identifiedBy: Self.changeActionID, for: .valueChanged)
        control.removeAction(identifiedBy: Self.submitActionID, for: .editingDidEndOnExit)
    }

    private func apply(_ props: [String: String], to view: UIView) {
        view.accessibilityLabel = props["accessibilityLabel"]
        let enabled = props["enabled"].flatMap(Bool.init) ?? true
        view.isUserInteractionEnabled = enabled
        (view as? UIControl)?.isEnabled = enabled
        let text = props["text"] ?? ""
        switch view {
        case let label as UILabel:
            label.text = text
        case let button as UIButton:
            button.setTitle(text, for: .normal)
        case let input as UITextField:
            input.placeholder = text
        default:
            break
        }
        let value = props["value"] ?? ""
        if let input = view as? UITextField, input.text != value { input.text = value }
        if let toggle = view as? UISwitch { toggle.isOn = Bool(value) ?? false }
    }

    private func bind(
        _ node: PVMUINode,
        to view: UIView,
        events: @escaping EventSink,
        awaitingAppear: Set<UInt32>,
        generation: UInt64
    ) {
        if node.events.contains("tap"), let control = view as? UIControl {
            control.addAction(
                UIAction(identifier: Self.tapActionID) { _ in
                    events(node.id, "tap", nil)
                },
                for: .touchUpInside
            )
        } else if node.events.contains("tap") {
            view.addGestureRecognizer(
                PVMClosureTapGestureRecognizer {
                    events(node.id, "tap", nil)
                }
            )
        }
        if node.events.contains("change"), let control = view as? UIControl {
            control.addAction(
                UIAction(identifier: Self.changeActionID) { [weak control] _ in
                    events(node.id, "change", control.flatMap(Self.value))
                },
                for: control is UITextField ? .editingChanged : .valueChanged
            )
        }
        if node.events.contains("submit"), let input = view as? UITextField {
            input.addAction(
                UIAction(identifier: Self.submitActionID) { [weak input] _ in
                    events(node.id, "submit", input?.text ?? "")
                },
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

    private static func value(of control: UIControl) -> String? {
        if let input = control as? UITextField { return input.text ?? "" }
        if let toggle = control as? UISwitch { return String(toggle.isOn) }
        return nil
    }

    private func cacheKey(for node: PVMUINode) -> String {
        node.type == "NativeSurface"
            ? "\(node.type):\(node.props["surfaceType"] ?? "")"
            : node.type
    }

    private final class CachedView {
        let key: String
        let revision: UInt64
        weak var view: UIView?

        init(key: String, revision: UInt64, view: UIView) {
            self.key = key
            self.revision = revision
            self.view = view
        }
    }

    private struct PendingBatch {
        let generation: UInt64
        let json: String
        let events: EventSink
        let errors: @MainActor (Error) -> Void
    }

    private static let backgroundDecodeThreshold = 32 * 1024
    private static let tapActionID = UIAction.Identifier("pvm.tap")
    private static let changeActionID = UIAction.Identifier("pvm.change")
    private static let submitActionID = UIAction.Identifier("pvm.submit")
}

@MainActor
private final class PVMCollectionListView: UICollectionView {
    private static let reuseIdentifier = "PVMNode"
    private var nodesByID: [UInt32: PVMUINode] = [:]
    private var render: (PVMUINode) -> UIView = { _ in UIView() }
    private var diffableDataSource: UICollectionViewDiffableDataSource<Int, UInt32>!

    init() {
        var configuration = UICollectionLayoutListConfiguration(appearance: .plain)
        configuration.showsSeparators = false
        super.init(
            frame: .zero,
            collectionViewLayout: UICollectionViewCompositionalLayout.list(
                using: configuration
            )
        )
        backgroundColor = .clear
        register(
            PVMCollectionCell.self,
            forCellWithReuseIdentifier: Self.reuseIdentifier
        )
        diffableDataSource = UICollectionViewDiffableDataSource(
            collectionView: self
        ) { [weak self] collectionView, indexPath, nodeID in
            guard let self, let node = self.nodesByID[nodeID] else { return nil }
            let cell = collectionView.dequeueReusableCell(
                withReuseIdentifier: Self.reuseIdentifier,
                for: indexPath
            ) as! PVMCollectionCell
            cell.install(self.render(node))
            return cell
        }
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var contentSize: CGSize {
        didSet {
            if oldValue != contentSize { invalidateIntrinsicContentSize() }
        }
    }

    override var intrinsicContentSize: CGSize {
        let hostHeight = window?.bounds.height ?? superview?.bounds.height ?? 0
        let desired = max(collectionViewLayout.collectionViewContentSize.height, 56)
        let maximum = hostHeight > 0 ? hostHeight : desired
        return CGSize(
            width: UIView.noIntrinsicMetric,
            height: min(desired, maximum)
        )
    }

    func replace(nodes: [PVMUINode], render: @escaping (PVMUINode) -> UIView) {
        let previous = nodesByID
        let identifiers = nodes.map(\.id)
        precondition(Set(identifiers).count == identifiers.count, "Duplicate PVM list node ID")
        nodesByID = Dictionary(uniqueKeysWithValues: nodes.map { ($0.id, $0) })
        self.render = render
        let existing = Set(diffableDataSource.snapshot().itemIdentifiers)
        let changed =
            identifiers.filter { identifier in
                existing.contains(identifier) &&
                    previous[identifier]?.revision != nodesByID[identifier]?.revision
            }
        var snapshot = NSDiffableDataSourceSnapshot<Int, UInt32>()
        snapshot.appendSections([0])
        snapshot.appendItems(identifiers, toSection: 0)
        if !changed.isEmpty {
            snapshot.reconfigureItems(changed)
        }
        diffableDataSource.apply(snapshot, animatingDifferences: false) { [weak self] in
            self?.invalidateIntrinsicContentSize()
        }
    }
}

@MainActor
private final class PVMCollectionCell: UICollectionViewCell {
    func install(_ rendered: UIView) {
        if contentView.subviews.count == 1 && contentView.subviews[0] === rendered { return }
        (rendered.superview as? UIStackView)?.removeArrangedSubview(rendered)
        rendered.removeFromSuperview()
        contentView.subviews.forEach { $0.removeFromSuperview() }
        rendered.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(rendered)
        NSLayoutConstraint.activate([
            rendered.leadingAnchor.constraint(equalTo: contentView.leadingAnchor),
            rendered.trailingAnchor.constraint(equalTo: contentView.trailingAnchor),
            rendered.topAnchor.constraint(equalTo: contentView.topAnchor),
            rendered.bottomAnchor.constraint(equalTo: contentView.bottomAnchor),
        ])
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
