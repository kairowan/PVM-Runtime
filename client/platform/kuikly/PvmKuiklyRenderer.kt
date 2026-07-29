package com.protectedvm.host.kuikly

/**
 * The Kuikly SDK changes independently from official Compose. This narrow port is implemented by
 * the app module and contract-tested without coupling the VM repository to one Kuikly release.
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
