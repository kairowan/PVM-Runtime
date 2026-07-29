package com.protectedvm.host

import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

object BasicAndroidCapabilities {
    fun install(
        context: Context,
        registry: CapabilityRegistry,
        executor: Executor = Executors.newCachedThreadPool(),
    ): PushInbox {
        registry.registerSync("ui.toast") { operation, arguments ->
            require(operation == "show" && arguments.length() == 1)
            Toast.makeText(context, arguments.getString(0), Toast.LENGTH_SHORT).show()
            "ok"
        }
        val preferences = context.getSharedPreferences("pvm_state", Context.MODE_PRIVATE)
        registry.registerAsync("storage.kv") { operation, arguments, complete ->
            require("app.preferences" in requireNotNull(registry.policy).storageScopes)
            when (operation) {
                "get" -> complete(preferences.getString(arguments.getString(0), "Not set") ?: "Not set")
                "set" -> {
                    preferences.edit().putString(arguments.getString(0), arguments.getString(1)).apply()
                    complete("ok")
                }
                "remove" -> {
                    preferences.edit().remove(arguments.getString(0)).apply()
                    complete("ok")
                }
                else -> error("Unsupported storage.kv operation: $operation")
            }
        }
        registry.registerAsync("network.http") { operation, arguments, complete ->
            require(operation == "get")
            val uri = URI(arguments.getString(0))
            val policy = requireNotNull(registry.policy)
            val host = requireNotNull(uri.host) { "URL has no host" }.lowercase()
            require(uri.scheme == "https" && host in policy.networkDomains) {
                "Network domain is not declared by the signed module"
            }
            executor.execute {
                runCatching {
                    val connection = uri.toURL().openConnection() as HttpURLConnection
                    connection.requestMethod = "GET"
                    connection.instanceFollowRedirects = false
                    connection.connectTimeout = 10_000
                    connection.readTimeout = 15_000
                    val status = connection.responseCode
                    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                    val body =
                        stream?.use {
                            val output = ByteArrayOutputStream()
                            val buffer = ByteArray(8_192)
                            while (true) {
                                val count = it.read(buffer)
                                if (count < 0) break
                                require(output.size() + count <= 1_048_576) { "HTTP body exceeds 1 MiB" }
                                output.write(buffer, 0, count)
                            }
                            output.toString(Charsets.UTF_8.name())
                        }.orEmpty()
                    JSONObject().put("ok", status in 200..299).put("status", status).put("body", body).toString()
                }.fold(
                    onSuccess = complete,
                    onFailure = {
                        complete(
                            JSONObject()
                                .put("ok", false)
                                .put("error", it.message ?: "network error")
                                .toString(),
                        )
                    },
                )
            }
        }
        return PushInbox(context, registry)
    }
}

class PushInbox(context: Context, registry: CapabilityRegistry) {
    private val preferences = context.getSharedPreferences("pvm_push_inbox", Context.MODE_PRIVATE)
    private val lock = Any()

    init {
        registry.registerAsync("push.inbox") { operation, _, complete ->
            require(operation == "drain")
            complete(drain().toString())
        }
    }

    fun enqueue(payload: JSONObject) {
        synchronized(lock) {
            val current = JSONArray(preferences.getString("events", "[]"))
            if (current.length() >= 100) current.remove(0)
            current.put(payload)
            preferences.edit().putString("events", current.toString()).apply()
        }
    }

    private fun drain(): JSONArray =
        synchronized(lock) {
            val current = JSONArray(preferences.getString("events", "[]"))
            preferences.edit().remove("events").apply()
            current
        }
}

class PermissionBroker(
    private val activity: Activity,
    registry: CapabilityRegistry,
    private val allowedPermissions: Set<String>,
) {
    private val nextRequest = AtomicInteger(41_000)
    private val pending = mutableMapOf<Int, (String) -> Unit>()

    init {
        registry.registerAsync("permission.request") { operation, arguments, complete ->
            require(operation == "request")
            val permission = arguments.getString(0)
            require(permission in allowedPermissions) { "Permission is not in the host allowlist" }
            if (activity.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED) {
                complete("granted")
            } else {
                val request = nextRequest.getAndIncrement()
                pending[request] = complete
                activity.requestPermissions(arrayOf(permission), request)
            }
        }
    }

    fun onRequestPermissionsResult(requestCode: Int, grantResults: IntArray): Boolean {
        val completion = pending.remove(requestCode) ?: return false
        completion(if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) "granted" else "denied")
        return true
    }
}
