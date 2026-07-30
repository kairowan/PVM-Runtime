package com.protectedvm.kmp

/**
 * Host-neutral API used from commonMain. Android, iOS and Harmony applications adapt their existing
 * PVM host to this small port; the protected bytecode platform remains the native target platform.
 */
public interface PvmRuntimePort {
    public fun start(request: PvmStartRequest): PvmSnapshot
    public fun dispatch(event: PvmEvent): PvmSnapshot
    public fun close()
}

public data class PvmStartRequest(
    val applicationId: String,
    val channel: String,
    val profile: String,
    val minimumRelease: ULong,
)

public data class PvmEvent(
    val nodeId: ULong,
    val name: String,
    val value: String? = null,
)

public data class PvmSnapshot(
    val revision: ULong,
    val treeJson: String,
)

/**
 * Enforces one start and prevents dispatch after close in shared code. Platform ports retain their
 * native thread/actor requirements and should be called from the UI thread.
 */
public class PvmRuntimeClient(private val port: PvmRuntimePort) : AutoCloseable {
    private var state: State = State.IDLE

    public fun start(request: PvmStartRequest): PvmSnapshot {
        check(state == State.IDLE) { "PVM runtime can only start once" }
        val snapshot = port.start(request)
        state = State.RUNNING
        return snapshot
    }

    public fun dispatch(event: PvmEvent): PvmSnapshot {
        check(state == State.RUNNING) { "PVM runtime is not running" }
        return port.dispatch(event)
    }

    override fun close() {
        if (state == State.CLOSED) return
        port.close()
        state = State.CLOSED
    }

    private enum class State {
        IDLE,
        RUNNING,
        CLOSED,
    }
}
