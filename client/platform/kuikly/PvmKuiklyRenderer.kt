package com.protectedvm.host.kuikly

/**
 * Prototype contract only. It is not part of the current Gradle/Swift builds and proves no
 * compatibility with a specific Kuikly release. A product must pin Kuikly and implement/test the port.
 */
interface PvmKuiklyPort<Node> {
    fun create(type: String, id: Long, props: Map<String, String>, children: List<Node>): Node
    fun bind(node: Node, events: Set<String>, emit: (String, String?) -> Unit)
    fun replace(root: Node)
}

data class PvmKuiklyNode(
    val type: String,
    val id: Long,
    val props: Map<String, String>,
    val events: Set<String>,
    val children: List<PvmKuiklyNode>,
)

class PvmKuiklyRenderer<Node>(private val port: PvmKuiklyPort<Node>) {
    fun replaceTree(root: PvmKuiklyNode, emit: (Long, String, String?) -> Unit) {
        port.replace(render(root, emit))
    }

    private fun render(value: PvmKuiklyNode, emit: (Long, String, String?) -> Unit): Node {
        val node = port.create(value.type, value.id, value.props, value.children.map { render(it, emit) })
        port.bind(node, value.events) { event, eventValue -> emit(value.id, event, eventValue) }
        return node
    }
}
