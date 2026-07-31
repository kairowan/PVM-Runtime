package com.protectedvm.host

import android.view.View
import android.widget.FrameLayout
import androidx.recyclerview.widget.RecyclerView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidViewRendererListTest {
    @Test
    fun wireV2PatchDoesNotRequireCompleteRoot() {
        val batch =
            UiNode.parseBatch(
                """
                {
                  "wireVersion": 2,
                  "operation": "patch",
                  "structureChanged": false,
                  "rootId": 1,
                  "rootType": "Column",
                  "rootRevision": 2,
                  "changed": [2],
                  "nodes": [{
                    "type": "Text",
                    "id": 2,
                    "revision": 2,
                    "props": {"text": "After"},
                    "events": [],
                    "children": []
                  }],
                  "revisions": [
                    {"id": 1, "revision": 2},
                    {"id": 2, "revision": 2}
                  ]
                }
                """.trimIndent(),
            )
        assertNull(batch.root)
        assertEquals(2L, batch.rootRevision)
        assertEquals("After", batch.changedNodes.single().props["text"])
    }

    @Test
    fun unchangedSiblingSkipsNativeRebind() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var descriptionWrites = 0
        instrumentation.runOnMainSync {
            val context = instrumentation.targetContext
            val root = FrameLayout(context)
            val surface =
                object : View(context) {
                    override fun setContentDescription(contentDescription: CharSequence?) {
                        descriptionWrites += 1
                        super.setContentDescription(contentDescription)
                    }
                }
            val renderer =
                AndroidViewRenderer(
                    context,
                    root,
                    NativeSurfaceRegistry { _, _, _ -> surface },
                )
            fun tree(rootRevision: Long, textRevision: Long, text: String) =
                UiNode(
                    type = "Column",
                    id = 1,
                    props = emptyMap(),
                    events = emptySet(),
                    children =
                        listOf(
                            UiNode(
                                type = "NativeSurface",
                                id = 2,
                                props =
                                    mapOf(
                                        "surfaceType" to "benchmark",
                                        "accessibilityLabel" to "Stable surface",
                                    ),
                                events = emptySet(),
                                children = emptyList(),
                                revision = 1,
                            ),
                            UiNode(
                                type = "Text",
                                id = 3,
                                props = mapOf("text" to text),
                                events = emptySet(),
                                children = emptyList(),
                                revision = textRevision,
                            ),
                        ),
                    revision = rootRevision,
                )
            renderer.replaceTree(tree(1, 1, "Before"), UiEventSink { _, _, _ -> })
            val writesAfterFirstRender = descriptionWrites
            renderer.replaceTree(tree(2, 2, "After"), UiEventSink { _, _, _ -> })
            assertEquals(writesAfterFirstRender, descriptionWrites)
        }
    }

    @Test
    fun largeListOnlyAttachesVisibleRows() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var attachedRows = 0
        instrumentation.runOnMainSync {
            val context = instrumentation.targetContext
            val root = FrameLayout(context)
            val renderer = AndroidViewRenderer(context, root)
            val rows =
                (0 until 1_000).map { index ->
                    UiNode(
                        type = "Text",
                        id = index.toLong() + 2,
                        props = mapOf("text" to "Row $index"),
                        events = emptySet(),
                        children = emptyList(),
                    )
                }
            renderer.replaceTree(
                UiNode(
                    type = "List",
                    id = 1,
                    props = emptyMap(),
                    events = emptySet(),
                    children = rows,
                ),
                UiEventSink { _, _, _ -> },
            )
            val width = context.resources.displayMetrics.widthPixels
            val height = context.resources.displayMetrics.heightPixels / 2
            root.measure(
                View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY),
            )
            root.layout(0, 0, width, height)
            attachedRows = (root.getChildAt(0) as RecyclerView).childCount
        }
        assertTrue(
            "RecyclerView should attach only its viewport, attached=$attachedRows",
            attachedRows in 1 until 1_000,
        )
    }
}
