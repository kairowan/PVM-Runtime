package com.protectedvm.host

import org.json.JSONArray
import org.json.JSONObject

data class RuntimePolicy(
    val applicationId: String,
    val release: Long,
    val profile: String,
    val platform: String,
    val capabilities: Set<String>,
    val capabilityVersions: Map<String, Int>,
    val networkDomains: Set<String>,
    val storageScopes: Set<String>,
) {
    companion object {
        fun parse(json: String): RuntimePolicy {
            val source = JSONObject(json)
            val versionObject = source.getJSONObject("capabilityVersions")
            val versions =
                buildMap {
                    val keys = versionObject.keys()
                    while (keys.hasNext()) {
                        val key = keys.next()
                        put(key, versionObject.getInt(key))
                    }
                }
            return RuntimePolicy(
                applicationId = source.getString("applicationId"),
                release = source.getLong("release"),
                profile = source.getString("profile"),
                platform = source.getString("platform"),
                capabilities = source.getJSONArray("capabilities").strings(),
                capabilityVersions = versions,
                networkDomains = source.getJSONArray("networkDomains").strings(),
                storageScopes = source.getJSONArray("storageScopes").strings(),
            )
        }
    }
}

data class UiNode(
    val type: String,
    val id: Long,
    val props: Map<String, String>,
    val events: Set<String>,
    val children: List<UiNode>,
) {
    companion object {
        fun parseBatch(json: String): UiNode {
            val batch = JSONObject(json)
            require(batch.getString("operation") == "replace") { "Unsupported UI batch" }
            return parse(batch.getJSONObject("root"))
        }

        private fun parse(source: JSONObject): UiNode {
            val propsObject = source.getJSONObject("props")
            val props = buildMap {
                val keys = propsObject.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    put(key, propsObject.getString(key))
                }
            }
            return UiNode(
                type = source.getString("type"),
                id = source.getLong("id"),
                props = props,
                events = source.getJSONArray("events").strings(),
                children = source.getJSONArray("children").objects().map(::parse),
            )
        }
    }
}

private fun JSONArray.strings(): Set<String> =
    buildSet {
        for (index in 0 until length()) add(getString(index))
    }

private fun JSONArray.objects(): List<JSONObject> =
    buildList {
        for (index in 0 until length()) add(getJSONObject(index))
    }
