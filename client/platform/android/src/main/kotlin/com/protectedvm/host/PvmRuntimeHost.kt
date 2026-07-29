package com.protectedvm.host

import android.os.Handler
import android.os.Looper
import android.util.Log

class PvmRuntimeHost(
    modulePath: String,
    publicKeyPath: String,
    applicationId: String,
    minimumRelease: Long,
    private val renderer: AndroidViewRenderer,
    private val capabilities: CapabilityRegistry,
    private val errors: (Throwable) -> Unit = { Log.e("ProtectedVM", "Runtime host error", it) },
) : UiEventSink, AutoCloseable {
    private val main = Handler(Looper.getMainLooper())
    private var handle: Long =
        nativeCreate(modulePath, publicKeyPath, applicationId, minimumRelease).also {
            require(it != 0L) { "Native runtime creation failed" }
        }

    val policy: RuntimePolicy =
        RuntimePolicy.parse(nativeMetadata(handle)).also {
            require(it.platform == "android") {
                "Android host rejected module for platform ${it.platform}"
            }
            capabilities.applyPolicy(it)
        }

    fun start() {
        checkMainThread()
        nativeStart(requireHandle())
    }

    override fun emit(nodeId: Long, event: String, value: String?) {
        checkMainThread()
        if (value == null) {
            nativeDispatch(requireHandle(), nodeId, eventCode(event))
        } else {
            nativeDispatchValue(requireHandle(), nodeId, eventCode(event), value)
        }
    }

    fun snapshotState(): ByteArray {
        checkMainThread()
        return nativeSnapshot(requireHandle())
    }

    fun restoreState(snapshot: ByteArray) {
        checkMainThread()
        nativeRestore(requireHandle(), snapshot)
    }

    fun cancelTasks() {
        checkMainThread()
        nativeCancelTasks(requireHandle())
    }

    override fun close() {
        checkMainThread()
        if (handle != 0L) {
            nativeDestroy(handle)
            handle = 0
        }
    }

    @Suppress("unused")
    private fun onNativeUiBatch(json: String) {
        checkMainThread()
        renderer.replaceTree(UiNode.parseBatch(json), this)
    }

    @Suppress("unused")
    private fun onNativeEffect(capability: String, operation: String, argumentsJson: String): String? =
        runCatching { capabilities.invokeSync(capability, operation, argumentsJson) }
            .onFailure(errors)
            .getOrNull()

    @Suppress("unused")
    private fun onNativeAsyncEffect(
        taskId: Long,
        capability: String,
        operation: String,
        argumentsJson: String,
    ) {
        capabilities.invokeAsync(capability, operation, argumentsJson) { result ->
            main.post {
                if (handle != 0L) {
                    runCatching { nativeComplete(handle, taskId, result) }.onFailure(errors)
                }
            }
        }
    }

    private fun requireHandle(): Long = handle.also { check(it != 0L) { "Runtime is closed" } }

    private fun checkMainThread() {
        check(Looper.myLooper() == Looper.getMainLooper()) {
            "PvmRuntimeHost must be called on Android's main thread"
        }
    }

    private fun eventCode(event: String): Int =
        when (event) {
            "tap" -> 1
            "change" -> 2
            "submit" -> 3
            "appear" -> 4
            else -> error("Unknown VM event: $event")
        }

    private external fun nativeCreate(
        modulePath: String,
        publicKeyPath: String,
        applicationId: String,
        minimumRelease: Long,
    ): Long
    private external fun nativeMetadata(handle: Long): String
    private external fun nativeStart(handle: Long)
    private external fun nativeDispatch(handle: Long, nodeId: Long, event: Int)
    private external fun nativeDispatchValue(handle: Long, nodeId: Long, event: Int, value: String)
    private external fun nativeComplete(handle: Long, taskId: Long, result: String)
    private external fun nativeCancelTasks(handle: Long)
    private external fun nativeSnapshot(handle: Long): ByteArray
    private external fun nativeRestore(handle: Long, state: ByteArray)
    private external fun nativeDestroy(handle: Long)

    companion object {
        init {
            System.loadLibrary("pvm_android")
        }
    }
}
