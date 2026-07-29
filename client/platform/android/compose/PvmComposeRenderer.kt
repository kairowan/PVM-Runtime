package com.protectedvm.host.compose

import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.painter.Painter
import com.protectedvm.host.UiNode

/**
 * Shared by Android Compose and CMP. Apps supply image and NativeSurface adapters so this module
 * does not pick a network loader, map SDK, player, or camera implementation.
 */
@Composable
fun PvmComposeTree(
    node: UiNode,
    emit: (Long, String, String?) -> Unit,
    image: @Composable (String) -> Painter,
    nativeSurface: @Composable (String, Long) -> Unit,
) {
    val click =
        if ("tap" in node.events) Modifier.clickable { emit(node.id, "tap", null) } else Modifier
    when (node.type) {
        "Text" -> BasicText(node.props["text"].orEmpty(), click)
        "Image" -> Image(image(node.props["source"].orEmpty()), null, click)
        "Row" -> Row(click) { node.children.forEach { PvmComposeTree(it, emit, image, nativeSurface) } }
        "Column", "List" ->
            Column(click) { node.children.forEach { PvmComposeTree(it, emit, image, nativeSurface) } }
        "Stack" ->
            Box(click) { node.children.forEach { PvmComposeTree(it, emit, image, nativeSurface) } }
        "Scroll" ->
            Column(click.verticalScroll(rememberScrollState())) {
                node.children.forEach { PvmComposeTree(it, emit, image, nativeSurface) }
            }
        "Button" -> BasicText(node.props["text"].orEmpty(), click)
        "Input" ->
            BasicTextField(
                value = node.props["value"].orEmpty(),
                onValueChange = { emit(node.id, "change", it) },
                modifier = click,
            )
        "Switch" ->
            BasicText(
                node.props["value"].orEmpty(),
                if ("change" in node.events) {
                    click.clickable {
                        emit(node.id, "change", (node.props["value"] != "true").toString())
                    }
                } else {
                    click
                },
            )
        "NativeSurface" -> nativeSurface(node.props["surfaceType"].orEmpty(), node.id)
        else -> error("Unsupported VM node type: ${node.type}")
    }
}
