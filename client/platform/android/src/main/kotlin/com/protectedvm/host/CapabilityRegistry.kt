package com.protectedvm.host

import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

fun interface SyncCapability {
    fun invoke(operation: String, arguments: JSONArray): String
}

fun interface AsyncCapability {
    fun invoke(operation: String, arguments: JSONArray, complete: (String) -> Unit)
}

class CapabilityRegistry {
    private val synchronous = ConcurrentHashMap<String, SyncCapability>()
    private val asynchronous = ConcurrentHashMap<String, AsyncCapability>()
    private val versions = ConcurrentHashMap<String, Int>()

    @Volatile
    var policy: RuntimePolicy? = null
        private set

    fun applyPolicy(value: RuntimePolicy) {
        value.capabilityVersions.forEach { (id, required) ->
            require((versions[id] ?: 0) >= required) {
                "Capability $id requires version $required; installed ${versions[id] ?: 0}"
            }
        }
        policy = value
    }

    fun registerSync(id: String, version: Int = 1, capability: SyncCapability) {
        registerVersion(id, version)
        check(synchronous.putIfAbsent(id, capability) == null) { "Duplicate capability: $id" }
    }

    fun registerAsync(id: String, version: Int = 1, capability: AsyncCapability) {
        registerVersion(id, version)
        check(asynchronous.putIfAbsent(id, capability) == null) { "Duplicate capability: $id" }
    }

    fun invokeSync(id: String, operation: String, argumentsJson: String): String {
        requireDeclared(id)
        return requireNotNull(synchronous[id]) { "Missing synchronous capability: $id" }
            .invoke(operation, JSONArray(argumentsJson))
    }

    fun invokeAsync(
        id: String,
        operation: String,
        argumentsJson: String,
        complete: (String) -> Unit,
    ) {
        try {
            requireDeclared(id)
            requireNotNull(asynchronous[id]) { "Missing asynchronous capability: $id" }
                .invoke(operation, JSONArray(argumentsJson), complete)
        } catch (error: Exception) {
            complete("""{"ok":false,"error":${JSONObject.quote(error.message ?: "capability error")}}""")
        }
    }

    private fun requireDeclared(id: String) {
        require(id in requireNotNull(policy) { "Runtime policy is not installed" }.capabilities) {
            "Module did not declare capability: $id"
        }
    }

    private fun registerVersion(id: String, version: Int) {
        require(version > 0) { "Capability version must be positive" }
        val existing = versions.putIfAbsent(id, version)
        check(existing == null || existing == version) {
            "Capability $id was registered with conflicting versions"
        }
    }
}
