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
    fun replaceTree(node: UiNode, events: UiEventSink) {
        checkMainThread()
        val rendered = create(node, events)
        root.removeAllViews()
        root.addView(
            rendered,
            ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ),
        )
    }

    private fun create(node: UiNode, sink: UiEventSink): View {
        val view =
            when (node.type) {
                "Text" -> TextView(context)
                "Image" -> ImageView(context)
                "Row" -> linear(LinearLayout.HORIZONTAL)
                "Column", "List" -> linear(LinearLayout.VERTICAL)
                "Stack" -> FrameLayout(context)
                "Scroll" ->
                    ScrollView(context).also { scroll ->
                        val content = linear(LinearLayout.VERTICAL)
                        node.children.forEach { content.addView(create(it, sink)) }
                        scroll.addView(content)
                    }
                "Button" -> Button(context)
                "Input" -> EditText(context)
                "Switch" -> Switch(context)
                "NativeSurface" ->
                    surfaces.create(context, node.props["surfaceType"].orEmpty(), node.id)
                else -> error("Unsupported VM node type: ${node.type}")
            }
        view.tag = node.id
        applyProperties(view, node.props)
        if (node.type != "Scroll" && view is ViewGroup) {
            node.children.forEach { view.addView(create(it, sink)) }
        }
        bindEvents(view, node, sink)
        return view
    }

    private fun linear(orientation: Int) =
        LinearLayout(context).apply {
            this.orientation = orientation
            gravity = Gravity.START
        }

    private fun applyProperties(view: View, props: Map<String, String>) {
        props["accessibilityLabel"]?.let { view.contentDescription = it }
        props["enabled"]?.let { view.isEnabled = it.toBooleanStrictOrNull() ?: true }
        props["text"]?.let { text ->
            when (view) {
                is TextView -> view.text = text
                else -> view.contentDescription = view.contentDescription ?: text
            }
        }
        props["value"]?.let { value ->
            when (view) {
                is EditText -> view.setText(value)
                is Switch -> view.isChecked = value.toBooleanStrictOrNull() ?: false
            }
        }
        if (view is ImageView) {
            // ponytail: image loading remains a host policy; the signed source is kept as a tag.
            view.tag = props["source"]
        }
    }

    private fun bindEvents(view: View, node: UiNode, sink: UiEventSink) {
        if ("tap" in node.events) view.setOnClickListener { sink.emit(node.id, "tap", null) }
        if ("submit" in node.events && view is EditText) {
            view.imeOptions = EditorInfo.IME_ACTION_DONE
            view.setOnEditorActionListener { _, _, _ ->
                sink.emit(node.id, "submit", view.text.toString())
                true
            }
        }
        if ("change" in node.events && view is EditText) {
            view.addTextChangedListener(
                object : TextWatcher {
                    override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
                    override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) =
                        sink.emit(node.id, "change", s?.toString().orEmpty())
                    override fun afterTextChanged(s: Editable?) = Unit
                },
            )
        }
        if ("change" in node.events && view is Switch) {
            view.setOnCheckedChangeListener { _, checked ->
                sink.emit(node.id, "change", checked.toString())
            }
        }
        if ("appear" in node.events) view.post { sink.emit(node.id, "appear", null) }
    }

    private fun checkMainThread() {
        check(android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) {
            "AndroidViewRenderer must run on the main thread"
        }
    }
}
