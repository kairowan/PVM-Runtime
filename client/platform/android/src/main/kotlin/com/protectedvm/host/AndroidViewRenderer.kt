package com.protectedvm.host

import android.content.Context
import android.graphics.Color
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import java.lang.ref.WeakReference
import java.util.Collections
import java.util.IdentityHashMap
import java.util.WeakHashMap

fun interface UiEventSink {
    fun emit(nodeId: Long, event: String, value: String?)
}

fun interface NativeSurfaceRegistry {
    fun create(context: Context, surfaceType: String, nodeId: Long): View
}

class AndroidViewRenderer(
    private val context: Context,
    private val root: ViewGroup,
    private val surfaces: NativeSurfaceRegistry = NativeSurfaceRegistry { current, type, _ ->
        View(current).apply {
            setBackgroundColor(Color.TRANSPARENT)
            contentDescription = "Missing native surface: $type"
        }
    },
) {
    private var renderGeneration = 0L
    private var visibleNodeIds = emptySet<Long>()
    private val appearedNodeIds = mutableSetOf<Long>()
    private val viewsById = mutableMapOf<Long, CachedView>()
    private val inputWatchers = WeakHashMap<EditText, TextWatcher>()
    private var renderedTree: UiNode? = null
    private var renderedRootId: Long? = null
    private var renderedRootType: String? = null
    private var renderedRootRevision: Long? = null

    fun replaceBatch(batch: UiBatch, events: UiEventSink) {
        checkMainThread()
        if (
            batch.structureChanged ||
            renderedTree == null ||
            renderedRootId != batch.rootId ||
            renderedRootType != batch.rootType
        ) {
            replaceTree(
                requireNotNull(batch.root) {
                    "A structural PVM update requires a complete root"
                },
                events,
            )
            return
        }
        if (renderedRootRevision == batch.rootRevision) return
        renderGeneration += 1
        val generation = renderGeneration
        val awaitingAppear = visibleNodeIds - appearedNodeIds
        batch.changedNodes.forEach { node ->
            applyChangedNode(node, events, awaitingAppear, generation)
        }
        renderedRootRevision = batch.rootRevision
    }

    fun replaceTree(node: UiNode, events: UiEventSink) {
        checkMainThread()
        val previous = renderedTree
        if (previous?.id == node.id && previous.type == node.type && previous.revision == node.revision) {
            return
        }
        renderGeneration += 1
        val generation = renderGeneration
        if (previous != null && previous.hasSameNativeShape(node)) {
            val awaitingAppear = visibleNodeIds - appearedNodeIds
            reconcileChanged(previous, node, events, awaitingAppear, generation)
            rememberRoot(node)
            return
        }
        val nextVisible = node.collectIds()
        appearedNodeIds.retainAll(nextVisible)
        visibleNodeIds = nextVisible
        val awaitingAppear = nextVisible - appearedNodeIds
        val focused = root.findFocus()
        val focusedTag = focused?.tag
        val selectionStart = (focused as? EditText)?.selectionStart ?: -1
        val selectionEnd = (focused as? EditText)?.selectionEnd ?: -1
        val rendered = reconcile(node, events, awaitingAppear, generation)
        viewsById.keys.retainAll(nextVisible)
        inputWatchers.keys.removeAll { (it.tag as? Long) !in nextVisible }
        if (root.childCount != 1 || root.getChildAt(0) !== rendered) {
            (rendered.parent as? ViewGroup)?.removeView(rendered)
            root.removeAllViews()
            root.addView(
                rendered,
                ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
        }
        if (focusedTag != null) {
            root.findViewWithTag<View>(focusedTag)?.let { replacement ->
                replacement.requestFocus()
                if (replacement is EditText && selectionStart >= 0 && selectionEnd >= 0) {
                    val length = replacement.text.length
                    replacement.setSelection(
                        selectionStart.coerceAtMost(length),
                        selectionEnd.coerceAtMost(length),
                    )
                }
            }
        }
        rememberRoot(node)
    }

    private fun rememberRoot(node: UiNode) {
        renderedTree = node
        renderedRootId = node.id
        renderedRootType = node.type
        renderedRootRevision = node.revision
    }

    private fun applyChangedNode(
        node: UiNode,
        sink: UiEventSink,
        awaitingAppear: Set<Long>,
        generation: Long,
    ) {
        val cached = requireNotNull(viewsById[node.id]) {
            "Changed PVM node ${node.id} has no native view"
        }
        val view = requireNotNull(cached.view.get()) {
            "Changed PVM node ${node.id} lost its native view"
        }
        check(cached.key == cacheKey(node)) {
            "Changed PVM node ${node.id} requires structural reconciliation"
        }
        val selection =
            (view as? EditText)
                ?.takeIf(View::hasFocus)
                ?.let { it.selectionStart to it.selectionEnd }
        prepareForReuse(view)
        applyProperties(view, node.props)
        if (node.type == "List") {
            (view as PvmRecyclerView).pvmAdapter.replace(
                node.children,
                sink,
                awaitingAppear,
                generation,
            )
        }
        bindEvents(view, node, sink, awaitingAppear, generation)
        selection?.let { (start, end) ->
            val length = view.text.length
            view.setSelection(start.coerceAtMost(length), end.coerceAtMost(length))
        }
        viewsById[node.id] = CachedView(cached.key, node.revision, cached.view)
    }

    private fun reconcileChanged(
        previous: UiNode,
        node: UiNode,
        sink: UiEventSink,
        awaitingAppear: Set<Long>,
        generation: Long,
    ) {
        if (previous.revision == node.revision) return
        val cached = viewsById[node.id]
        val view = cached?.view?.get()
        check(cached?.key == cacheKey(node) && view != null) {
            "Stable PVM node ${node.id} lost its native view"
        }
        if (previous.props != node.props || previous.events != node.events) {
            prepareForReuse(view)
            applyProperties(view, node.props)
            bindEvents(view, node, sink, awaitingAppear, generation)
        }
        if (node.type == "List") {
            (view as PvmRecyclerView).pvmAdapter.replace(
                node.children,
                sink,
                awaitingAppear,
                generation,
            )
        } else {
            previous.children.zip(node.children).forEach { (oldChild, newChild) ->
                reconcileChanged(oldChild, newChild, sink, awaitingAppear, generation)
            }
        }
        viewsById[node.id] = CachedView(cached.key, node.revision, cached.view)
    }

    private fun reconcile(
        node: UiNode,
        sink: UiEventSink,
        awaitingAppear: Set<Long>,
        generation: Long,
    ): View {
        val cached = viewsById[node.id]
        val key = cacheKey(node)
        val reusable = cached?.view?.get()
        if (cached?.key == key && cached.revision == node.revision && reusable != null) {
            return reusable
        }
        val view =
            if (cached?.key == key && reusable != null) {
                reusable
            } else {
                createShell(node)
            }
        view.tag = node.id
        prepareForReuse(view)
        applyProperties(view, node.props)
        when {
            node.type == "Scroll" ->
                reconcileChildren(
                    (view as ScrollView).getChildAt(0) as ViewGroup,
                    node.children,
                    sink,
                    awaitingAppear,
                    generation,
                )
            node.type == "List" ->
                (view as PvmRecyclerView).pvmAdapter.replace(
                    node.children,
                    sink,
                    awaitingAppear,
                    generation,
                )
            view is ViewGroup ->
                reconcileChildren(view, node.children, sink, awaitingAppear, generation)
        }
        bindEvents(view, node, sink, awaitingAppear, generation)
        viewsById[node.id] = CachedView(key, node.revision, WeakReference(view))
        return view
    }

    private fun createShell(node: UiNode): View =
        when (node.type) {
            "Text" -> TextView(context)
            // ponytail: the target app owns image loading and its signed-source policy.
            "Image" -> ImageView(context)
            "Row" -> linear(LinearLayout.HORIZONTAL)
            "Column" -> linear(LinearLayout.VERTICAL)
            "List" ->
                PvmRecyclerView()
            "Stack" -> FrameLayout(context)
            "Scroll" ->
                ScrollView(context).also { scroll ->
                    scroll.addView(
                        linear(LinearLayout.VERTICAL),
                        ViewGroup.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.WRAP_CONTENT,
                        ),
                    )
                }
            "Button" -> Button(context)
            "Input" -> EditText(context)
            "Switch" -> Switch(context)
            "NativeSurface" ->
                surfaces.create(context, node.props["surfaceType"].orEmpty(), node.id)
            else -> error("Unsupported VM node type: ${node.type}")
        }

    private fun reconcileChildren(
        parent: ViewGroup,
        nodes: List<UiNode>,
        sink: UiEventSink,
        awaitingAppear: Set<Long>,
        generation: Long,
    ) {
        val desired = nodes.map { reconcile(it, sink, awaitingAppear, generation) }
        val desiredViews =
            Collections.newSetFromMap(IdentityHashMap<View, Boolean>()).apply {
                addAll(desired)
            }
        for (index in parent.childCount - 1 downTo 0) {
            if (parent.getChildAt(index) !in desiredViews) parent.removeViewAt(index)
        }
        desired.forEachIndexed { index, child ->
            if (
                parent is LinearLayout &&
                parent.orientation == LinearLayout.VERTICAL &&
                parent.parent !is ScrollView &&
                child is PvmRecyclerView
            ) {
                child.layoutParams =
                    LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        0,
                        1f,
                    )
            }
            if (index < parent.childCount && parent.getChildAt(index) === child) {
                return@forEachIndexed
            }
            // ponytail: stable order is O(n); move-heavy collections belong in
            // RecyclerView, whose DiffUtil handles arbitrary reordering.
            (child.parent as? ViewGroup)?.removeView(child)
            parent.addView(child, index)
        }
    }

    private fun linear(orientation: Int) =
        LinearLayout(context).apply {
            this.orientation = orientation
            gravity = Gravity.START
        }

    private fun prepareForReuse(view: View) {
        view.setOnClickListener(null)
        if (view is EditText) {
            inputWatchers.remove(view)?.let(view::removeTextChangedListener)
            view.setOnEditorActionListener(null)
        }
        if (view is Switch) view.setOnCheckedChangeListener(null)
    }

    private fun applyProperties(view: View, props: Map<String, String>) {
        view.contentDescription = props["accessibilityLabel"]
        view.isEnabled = props["enabled"]?.toBooleanStrictOrNull() ?: true
        val text = props["text"].orEmpty()
        when (view) {
            is EditText -> view.hint = text
            is TextView -> view.text = text
            else -> if (view.contentDescription == null && text.isNotEmpty()) {
                view.contentDescription = text
            }
        }
        val value = props["value"].orEmpty()
        when (view) {
            is EditText -> if (view.text.toString() != value) view.setText(value)
            is Switch -> view.isChecked = value.toBooleanStrictOrNull() ?: false
        }
    }

    private fun bindEvents(
        view: View,
        node: UiNode,
        sink: UiEventSink,
        awaitingAppear: Set<Long>,
        generation: Long,
    ) {
        if ("tap" in node.events) view.setOnClickListener { sink.emit(node.id, "tap", null) }
        if ("submit" in node.events && view is EditText) {
            view.imeOptions = EditorInfo.IME_ACTION_DONE
            view.setOnEditorActionListener { _, _, _ ->
                sink.emit(node.id, "submit", view.text.toString())
                true
            }
        }
        if ("change" in node.events && view is EditText) {
            val watcher =
                object : TextWatcher {
                    override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
                    override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) =
                        sink.emit(node.id, "change", s?.toString().orEmpty())
                    override fun afterTextChanged(s: Editable?) = Unit
                }
            inputWatchers[view] = watcher
            view.addTextChangedListener(watcher)
        }
        if ("change" in node.events && view is Switch) {
            view.setOnCheckedChangeListener { _, checked ->
                sink.emit(node.id, "change", checked.toString())
            }
        }
        if ("appear" in node.events && node.id in awaitingAppear) {
            view.post {
                if (
                    generation == renderGeneration &&
                    node.id in visibleNodeIds &&
                    appearedNodeIds.add(node.id)
                ) {
                    sink.emit(node.id, "appear", null)
                }
            }
        }
    }

    private fun checkMainThread() {
        check(android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) {
            "AndroidViewRenderer must run on the main thread"
        }
    }

    private fun UiNode.collectIds(): Set<Long> {
        val result = HashSet<Long>()
        val pending = ArrayDeque<UiNode>()
        pending.add(this)
        while (pending.isNotEmpty()) {
            val current = pending.removeLast()
            result += current.id
            current.children.forEach(pending::addLast)
        }
        return result
    }

    private fun UiNode.hasSameNativeShape(other: UiNode): Boolean {
        if (
            id != other.id ||
            type != other.type ||
            children.size != other.children.size ||
            cacheKey(this) != cacheKey(other)
        ) {
            return false
        }
        if (revision == other.revision) return true
        return children.indices.all { index ->
            children[index].hasSameNativeShape(other.children[index])
        }
    }

    private fun cacheKey(node: UiNode): String =
        if (node.type == "NativeSurface") {
            "${node.type}:${node.props["surfaceType"].orEmpty()}"
        } else {
            node.type
        }

    private data class CachedView(
        val key: String,
        val revision: Long,
        val view: WeakReference<View>,
    )

    private inner class PvmRecyclerView : RecyclerView(context) {
        val pvmAdapter = PvmListAdapter()

        init {
            layoutManager = LinearLayoutManager(context)
            adapter = pvmAdapter
            itemAnimator = null
            isVerticalScrollBarEnabled = true
        }

        override fun onMeasure(widthSpec: Int, heightSpec: Int) {
            val mode = View.MeasureSpec.getMode(heightSpec)
            if (mode == View.MeasureSpec.EXACTLY) {
                super.onMeasure(widthSpec, heightSpec)
                return
            }
            // ponytail: the DSL has no height constraint yet, so cap an unbounded list
            // to its host viewport; explicit layout sizing can replace this when added.
            val hostHeight = root.height.takeIf { it > 0 } ?: resources.displayMetrics.heightPixels
            val requested =
                if (mode == View.MeasureSpec.AT_MOST) {
                    minOf(View.MeasureSpec.getSize(heightSpec), hostHeight)
                } else {
                    hostHeight
                }
            super.onMeasure(
                widthSpec,
                View.MeasureSpec.makeMeasureSpec(requested, View.MeasureSpec.AT_MOST),
            )
        }
    }

    private inner class PvmListAdapter :
        ListAdapter<UiNode, PvmListViewHolder>(PvmNodeDiff) {
        private var sink = UiEventSink { _, _, _ -> }
        private var awaitingAppear = emptySet<Long>()
        private var generation = 0L

        init {
            setHasStableIds(true)
        }

        fun replace(
            nodes: List<UiNode>,
            sink: UiEventSink,
            awaitingAppear: Set<Long>,
            generation: Long,
        ) {
            this.sink = sink
            this.awaitingAppear = awaitingAppear
            this.generation = generation
            submitList(nodes.toList())
        }

        override fun getItemId(position: Int): Long = getItem(position).id

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): PvmListViewHolder =
            PvmListViewHolder(
                FrameLayout(parent.context).apply {
                    layoutParams =
                        RecyclerView.LayoutParams(
                            RecyclerView.LayoutParams.MATCH_PARENT,
                            RecyclerView.LayoutParams.WRAP_CONTENT,
                        )
                },
            )

        override fun onBindViewHolder(holder: PvmListViewHolder, position: Int) {
            holder.bind(
                reconcile(getItem(position), sink, awaitingAppear, generation),
            )
        }
    }

    private class PvmListViewHolder(
        private val container: FrameLayout,
    ) : RecyclerView.ViewHolder(container) {
        fun bind(rendered: View) {
            if (container.childCount == 1 && container.getChildAt(0) === rendered) return
            (rendered.parent as? ViewGroup)?.removeView(rendered)
            container.removeAllViews()
            container.addView(
                rendered,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT,
                ),
            )
        }
    }

    private object PvmNodeDiff : DiffUtil.ItemCallback<UiNode>() {
        override fun areItemsTheSame(oldItem: UiNode, newItem: UiNode): Boolean =
            oldItem.id == newItem.id && oldItem.type == newItem.type

        override fun areContentsTheSame(oldItem: UiNode, newItem: UiNode): Boolean =
            oldItem.revision == newItem.revision
    }
}
