package com.protectedvm.demo

import android.app.Activity
import android.os.Bundle
import android.system.Os
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.FrameLayout
import android.widget.TextView
import com.protectedvm.host.AndroidViewRenderer
import com.protectedvm.host.BasicAndroidCapabilities
import com.protectedvm.host.CapabilityRegistry
import com.protectedvm.host.PvmCrypto
import com.protectedvm.host.PvmRuntimeHost
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.roundToInt

class MainActivity : Activity() {
    private var runtime: PvmRuntimeHost? = null
    private lateinit var root: FrameLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val contentPadding = (16 * resources.displayMetrics.density).roundToInt()
        root =
            FrameLayout(this).apply {
                layoutParams =
                    ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT,
                    )
                setOnApplyWindowInsetsListener { view, insets ->
                    val bars = insets.getInsets(WindowInsets.Type.systemBars())
                    view.setPadding(
                        bars.left + contentPadding,
                        bars.top + contentPadding,
                        bars.right + contentPadding,
                        bars.bottom + contentPadding,
                    )
                    insets
                }
            }
        setContentView(root)
        window.insetsController?.setSystemBarsAppearance(
            WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
            WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
        )
        runCatching { startRuntime() }.onFailure(::showError)
    }

    override fun onStop() {
        runtime?.let { host ->
            runCatching { persistState(host.snapshotState()) }
        }
        super.onStop()
    }

    override fun onDestroy() {
        runtime?.close()
        runtime = null
        super.onDestroy()
    }

    private fun startRuntime() {
        val bootstrap =
            assets.open("bootstrap.json").bufferedReader().use { JSONObject(it.readText()) }
        require(
            bootstrap.getString("platform") == "android" &&
                bootstrap.getString("profile") == "offline_sealed" &&
                bootstrap.getString("mode") == "bundled",
        ) { "Demo requires the Android Offline Sealed delivery" }
        val applicationId = bootstrap.getString("applicationId")
        require(applicationId == packageName) {
            "Bootstrap applicationId $applicationId does not match $packageName"
        }
        val module = copyAsset("module.pvm")
        val publicKey = copyAsset("module-public-key.pem")
        verifyPackage(module, publicKey)
        val capabilities = CapabilityRegistry()
        BasicAndroidCapabilities.install(this, capabilities)
        val host =
            PvmRuntimeHost(
                modulePath = module.absolutePath,
                publicKeyPath = publicKey.absolutePath,
                applicationId = applicationId,
                expectedChannel = bootstrap.getString("channel"),
                expectedProfile = bootstrap.getString("profile"),
                minimumRelease = bootstrap.getLong("release"),
                renderer = AndroidViewRenderer(this, root),
                capabilities = capabilities,
                errors = ::showError,
            )
        try {
            File(filesDir, STATE_FILE).takeIf(File::isFile)?.let { state ->
                runCatching { host.restoreState(state.readBytes()) }
                    .onFailure { state.delete() }
            }
            host.start()
            runtime = host
        } catch (error: Throwable) {
            host.close()
            throw error
        }
    }

    private fun copyAsset(name: String): File {
        val destination = File(filesDir, name)
        assets.open(name).use { input ->
            destination.outputStream().use(input::copyTo)
        }
        return destination
    }

    private fun verifyPackage(module: File, publicKey: File) {
        val packageBytes = module.readBytes()
        require(
            packageBytes.size >= 14 &&
                packageBytes.copyOfRange(0, 4).contentEquals("PVMP".toByteArray()),
        )
        val header = ByteBuffer.wrap(packageBytes).order(ByteOrder.LITTLE_ENDIAN)
        val payloadSize = header.getInt(8)
        val signatureSize = header.getShort(12).toInt() and 0xffff
        require(
            payloadSize > 0 &&
                signatureSize == 64 &&
                14 + payloadSize + signatureSize == packageBytes.size,
        )
        check(
            PvmCrypto.verify(
                publicKey.absolutePath,
                packageBytes.copyOfRange(14, 14 + payloadSize),
                packageBytes.copyOfRange(14 + payloadSize, packageBytes.size),
            ),
        ) { PvmCrypto.lastFailure ?: "Android platform Ed25519 verification failed" }
    }

    private fun persistState(state: ByteArray) {
        val destination = File(filesDir, STATE_FILE)
        val temporary = File(filesDir, "$STATE_FILE.tmp")
        try {
            FileOutputStream(temporary).use {
                it.write(state)
                it.fd.sync()
            }
            Os.rename(temporary.absolutePath, destination.absolutePath)
        } finally {
            temporary.delete()
        }
    }

    private fun showError(error: Throwable) {
        root.removeAllViews()
        root.addView(
            TextView(this).apply {
                text = "PVM Runtime failed:\n${error.message}"
                setTextIsSelectable(true)
            },
        )
    }

    private companion object {
        const val STATE_FILE = "counter.state"
    }
}
