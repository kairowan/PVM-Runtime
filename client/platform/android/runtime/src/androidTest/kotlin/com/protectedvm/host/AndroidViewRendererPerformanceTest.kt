package com.protectedvm.host

import android.os.SystemClock
import android.util.Log
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidViewRendererPerformanceTest {
    @Test
    fun incrementalCommitBeatsFullNativeRebind() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        lateinit var result: BenchmarkResult
        instrumentation.runOnMainSync {
            val context = instrumentation.targetContext
            val rendererRoot = FrameLayout(context)
            val renderer = AndroidViewRenderer(context, rendererRoot)
            val staticLabels = List(NODE_COUNT) { "Stable node $it" }
            val updates =
                List(WARMUP_COUNT + SAMPLE_COUNT + 1) { update ->
                    UiNode(
                        type = "Column",
                        id = 1,
                        props = emptyMap(),
                        events = emptySet(),
                        children =
                            List(NODE_COUNT) { index ->
                                UiNode(
                                    type = "Text",
                                    id = index.toLong() + 2,
                                    props =
                                        mapOf(
                                            "text" to
                                                if (index == CHANGED_INDEX) {
                                                    "Dynamic $update"
                                                } else {
                                                    staticLabels[index]
                                                },
                                        ),
                                    events = emptySet(),
                                    children = emptyList(),
                                    revision =
                                        if (index == CHANGED_INDEX) {
                                            update.toLong() + 1
                                        } else {
                                            1
                                        },
                                )
                            },
                        revision = update.toLong() + 1,
                    )
                }
            val sink = UiEventSink { _, _, _ -> }
            renderer.replaceTree(updates.first(), sink)

            val fullNative =
                List(NODE_COUNT) { index ->
                    TextView(context).apply { text = staticLabels[index] }
                }
            val directNative =
                TextView(context).apply { text = "Dynamic 0" }
            val fullNativeRoot =
                LinearLayout(context).apply {
                    orientation = LinearLayout.VERTICAL
                    fullNative.forEach(::addView)
                }
            check(fullNativeRoot.childCount == NODE_COUNT)

            repeat(WARMUP_COUNT) { update ->
                renderer.replaceBatch(updates[update + 1].incrementalBatch(), sink)
                rebindAll(fullNative, staticLabels, update)
                directNative.text = "Dynamic $update"
            }

            val pvmSamples = LongArray(SAMPLE_COUNT)
            val fullNativeSamples = LongArray(SAMPLE_COUNT)
            val optimizedNativeSamples = LongArray(SAMPLE_COUNT)
            repeat(SAMPLE_COUNT) { sample ->
                val update = WARMUP_COUNT + sample + 1
                when (sample % 3) {
                    0 -> {
                        pvmSamples[sample] =
                            timed {
                                renderer.replaceBatch(
                                    updates[update].incrementalBatch(),
                                    sink,
                                )
                            }
                        fullNativeSamples[sample] =
                            timed { rebindAll(fullNative, staticLabels, update) }
                        optimizedNativeSamples[sample] =
                            timed { directNative.text = "Dynamic $update" }
                    }
                    1 -> {
                        fullNativeSamples[sample] =
                            timed { rebindAll(fullNative, staticLabels, update) }
                        optimizedNativeSamples[sample] =
                            timed { directNative.text = "Dynamic $update" }
                        pvmSamples[sample] =
                            timed {
                                renderer.replaceBatch(
                                    updates[update].incrementalBatch(),
                                    sink,
                                )
                            }
                    }
                    else -> {
                        optimizedNativeSamples[sample] =
                            timed { directNative.text = "Dynamic $update" }
                        pvmSamples[sample] =
                            timed {
                                renderer.replaceBatch(
                                    updates[update].incrementalBatch(),
                                    sink,
                                )
                            }
                        fullNativeSamples[sample] =
                            timed { rebindAll(fullNative, staticLabels, update) }
                    }
                }
            }
            result =
                BenchmarkResult(
                    pvm = summarize(pvmSamples),
                    fullNative = summarize(fullNativeSamples),
                    optimizedNative = summarize(optimizedNativeSamples),
                )
        }

        val json =
            JSONObject()
                .put("device", android.os.Build.MODEL)
                .put("sdk", android.os.Build.VERSION.SDK_INT)
                .put("nodes", NODE_COUNT)
                .put("samples", SAMPLE_COUNT)
                .put("unit", "microseconds")
                .put("scope", "main-thread native commit; model construction and wire decode excluded")
                .put("pvmIncremental", result.pvm.toJson())
                .put("nativeFullRebind", result.fullNative.toJson())
                .put("nativeOptimizedLeafUpdate", result.optimizedNative.toJson())
                .put(
                    "pvmVsFullRebindP95Ratio",
                    result.pvm.p95Micros.toDouble() / result.fullNative.p95Micros,
                )
        Log.i(LOG_TAG, json.toString())

        assertTrue(
            "PVM p95 ${result.pvm.p95Micros}us must beat full native rebind " +
                "${result.fullNative.p95Micros}us",
            result.pvm.p95Micros < result.fullNative.p95Micros,
        )
        assertTrue(
            "PVM p95 ${result.pvm.p95Micros}us exceeded one 60Hz frame",
            result.pvm.p95Micros < FRAME_BUDGET_MICROS,
        )
    }

    private fun rebindAll(views: List<TextView>, labels: List<String>, update: Int) {
        views.forEachIndexed { index, view ->
            view.text = if (index == CHANGED_INDEX) "Dynamic $update" else labels[index]
        }
    }

    private fun UiNode.incrementalBatch() =
        UiBatch(
            root = null,
            structureChanged = false,
            changedNodes = listOf(children[CHANGED_INDEX]),
            rootId = id,
            rootType = type,
            rootRevision = revision,
            revisions =
                mapOf(
                    id to revision,
                    children[CHANGED_INDEX].id to children[CHANGED_INDEX].revision,
                ),
        )

    private fun timed(block: () -> Unit): Long {
        val started = SystemClock.elapsedRealtimeNanos()
        block()
        return SystemClock.elapsedRealtimeNanos() - started
    }

    private fun summarize(samples: LongArray): Stats {
        val sorted = samples.sortedArray()
        return Stats(
            medianMicros = sorted[sorted.size / 2] / 1_000,
            p95Micros = sorted[(sorted.size * 95 / 100).coerceAtMost(sorted.lastIndex)] / 1_000,
        )
    }

    private data class BenchmarkResult(
        val pvm: Stats,
        val fullNative: Stats,
        val optimizedNative: Stats,
    )

    private data class Stats(
        val medianMicros: Long,
        val p95Micros: Long,
    ) {
        fun toJson() =
            JSONObject()
                .put("median", medianMicros)
                .put("p95", p95Micros)
    }

    private companion object {
        const val NODE_COUNT = 240
        const val CHANGED_INDEX = NODE_COUNT / 2
        const val WARMUP_COUNT = 20
        const val SAMPLE_COUNT = 180
        const val FRAME_BUDGET_MICROS = 16_667L
        const val LOG_TAG = "PvmRenderBenchmark"
    }
}
