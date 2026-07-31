package com.protectedvm.host

import org.json.JSONArray
import org.json.JSONObject

data class RuntimePolicy(
    val applicationId: String,
    val channel: String,
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
                channel = source.getString("channel"),
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
    val revision: Long = 1,
) {
    companion object {
        fun parseBatch(json: String): UiBatch {
            val batch = JSONObject(json)
            val operation = batch.getString("operation")
            require(operation == "replace" || operation == "patch") { "Unsupported UI batch" }
            val wireVersion = batch.optInt("wireVersion", 1)
            require(operation != "patch" || wireVersion == 2) { "Patch requires UI wire v2" }
            val structureChanged = batch.optBoolean("structureChanged", true)
            require(operation != "patch" || !structureChanged) {
                "Structural UI changes require a complete root"
            }
            val root =
                batch.optJSONObject("root")?.let {
                    parse(it, HashMap())
                }
            require(operation != "replace" || root != null) { "Replacement root is missing" }
            val changedIds = batch.optJSONArray("changed")?.longs().orEmpty()
            require(changedIds.distinct().size == changedIds.size) {
                "Duplicate changed UI node id"
            }
            val changedById =
                if (operation == "replace") {
                    root!!.flatten().associateBy(UiNode::id)
                } else {
                    val changedNodes =
                        batch.getJSONArray("nodes")
                        .objects()
                        .map { parse(it, HashMap()) }
                    require(changedNodes.map(UiNode::id).distinct().size == changedNodes.size) {
                        "Duplicate changed UI node payload"
                    }
                    changedNodes.associateBy(UiNode::id)
                }
            val revisions =
                buildMap {
                    batch.optJSONArray("revisions")?.objects().orEmpty().forEach { item ->
                        val id = item.getLong("id")
                        require(put(id, item.getLong("revision")) == null) {
                            "Duplicate UI revision id $id"
                        }
                    }
                }
            return UiBatch(
                root = root,
                structureChanged = structureChanged,
                changedNodes = changedIds.map { id ->
                    requireNotNull(changedById[id]) { "Changed UI node $id is missing" }
                },
                rootId = root?.id ?: batch.getLong("rootId"),
                rootType = root?.type ?: batch.getString("rootType"),
                rootRevision = root?.revision ?: batch.getLong("rootRevision"),
                revisions = revisions,
            )
        }

        private fun parse(source: JSONObject, nodesById: MutableMap<Long, UiNode>): UiNode {
            val propsObject = source.getJSONObject("props")
            val props = buildMap {
                val keys = propsObject.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    put(key, propsObject.getString(key))
                }
            }
            val node =
                UiNode(
                type = source.getString("type"),
                id = source.getLong("id"),
                revision = source.getLong("revision"),
                props = props,
                events = source.getJSONArray("events").strings(),
                children =
                    source
                        .getJSONArray("children")
                        .objects()
                        .map { child -> parse(child, nodesById) },
            )
            require(nodesById.put(node.id, node) == null) {
                "Duplicate UI node id ${node.id}"
            }
            return node
        }

        private fun UiNode.flatten(): Sequence<UiNode> =
            sequence {
                yield(this@flatten)
                children.forEach { yieldAll(it.flatten()) }
            }
    }
}

data class UiBatch(
    val root: UiNode?,
    val structureChanged: Boolean,
    val changedNodes: List<UiNode>,
    val rootId: Long = requireNotNull(root).id,
    val rootType: String = requireNotNull(root).type,
    val rootRevision: Long = requireNotNull(root).revision,
    val revisions: Map<Long, Long> = emptyMap(),
)

private fun JSONArray.strings(): Set<String> =
    buildSet {
        for (index in 0 until length()) add(getString(index))
    }

private fun JSONArray.objects(): List<JSONObject> =
    buildList {
        for (index in 0 until length()) add(getJSONObject(index))
    }

private fun JSONArray.longs(): List<Long> =
    buildList {
        for (index in 0 until length()) add(getLong(index))
    }
