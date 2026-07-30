package com.protectedvm.kmp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class PvmRuntimeTest {
    @Test
    fun lifecycleRejectsInvalidCallsAndCloseIsIdempotent() {
        val port = FakePort()
        val client = PvmRuntimeClient(port)
        assertFailsWith<IllegalStateException> {
            client.dispatch(PvmEvent(1u, "tap"))
        }
        assertEquals(1u, client.start(PvmStartRequest("app", "production", "offline_sealed", 1u)).revision)
        assertEquals(2u, client.dispatch(PvmEvent(1u, "tap")).revision)
        assertFailsWith<IllegalStateException> {
            client.start(PvmStartRequest("app", "production", "offline_sealed", 1u))
        }
        client.close()
        client.close()
        assertEquals(1, port.closeCount)
        assertFailsWith<IllegalStateException> {
            client.dispatch(PvmEvent(1u, "tap"))
        }
    }

    @Test
    fun failedCloseCanBeRetried() {
        val port = FakePort(closeFailures = 1)
        val client = PvmRuntimeClient(port)
        client.start(PvmStartRequest("app", "production", "offline_sealed", 1u))
        assertFailsWith<IllegalStateException> { client.close() }
        client.close()
        assertEquals(2, port.closeCount)
    }

    private class FakePort(private var closeFailures: Int = 0) : PvmRuntimePort {
        var revision = 0uL
        var closeCount = 0

        override fun start(request: PvmStartRequest) = PvmSnapshot(++revision, "{}")

        override fun dispatch(event: PvmEvent) = PvmSnapshot(++revision, "{}")

        override fun close() {
            closeCount += 1
            if (closeFailures > 0) {
                closeFailures -= 1
                error("close failed")
            }
        }
    }
}
