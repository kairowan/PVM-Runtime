package com.protectedvm.host

import android.system.Os
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URI
import java.security.MessageDigest

class PvmModuleStore(
    private val root: File,
    private val publicKeyPath: String,
    private val applicationId: String,
    private val channel: String,
    private val profile: String,
    serverBase: String,
    private val activationToken: String? = null,
    private val installationId: String? = null,
    allowHttpLocalhost: Boolean = false,
    private val minimumRelease: Long = 0,
) {
    private val server = URI(serverBase.trimEnd('/'))
    private val modules = File(root, "modules")
    private val currentFile = File(root, "current.json")

    init {
        require(
            server.scheme == "https" ||
                (
                    allowHttpLocalhost &&
                        server.scheme == "http" &&
                        server.host in setOf("127.0.0.1", "localhost")
                    )
        ) { "Module service must use HTTPS" }
        require(
            SEGMENT.matches(applicationId) &&
                SEGMENT.matches(channel) &&
                applicationId !in setOf(".", "..") &&
                channel !in setOf(".", "..")
        )
        require(profile in PROFILES)
        require(minimumRelease >= 0)
        modules.mkdirs()
    }

    fun lastKnownGood(): File? {
        val state = readState() ?: return null
        if (state.release < minimumRelease) return null
        return File(modules, "${state.sha256}.pvm").takeIf {
            it.isFile && it.length() in 1..MAX_MODULE_BYTES && it.hasSha256(state.sha256)
        }?.also {
            runCatching { Os.chmod(it.absolutePath, 0b110000000) }
        }
    }

    /**
     * Runs on a worker thread. A refresh failure never removes or replaces last-known-good.
     */
    fun refresh(): File {
        check(android.os.Looper.myLooper() != android.os.Looper.getMainLooper()) {
            "Module refresh must not block the UI thread"
        }
        val previous = readState()
        return runCatching { download(previous) }.getOrElse { error ->
            lastKnownGood() ?: throw error
        }
    }

    private fun download(previous: State?): File {
        val manifestPath = "/v1/apps/$applicationId/$channel/android/$profile/manifest"
        val connection = open(server.resolve(manifestPath))
        val cached = lastKnownGood()
        previous
            ?.takeIf { cached != null && it.release >= minimumRelease }
            ?.etag
            ?.takeIf(String::isNotEmpty)
            ?.let {
            connection.setRequestProperty("If-None-Match", it)
        }
        installationId?.let { connection.setRequestProperty("X-PVM-Installation-ID", it) }
        connection.connect()
        if (connection.responseCode == HttpURLConnection.HTTP_NOT_MODIFIED) {
            return requireNotNull(lastKnownGood()) { "Server returned 304 without a cached module" }
        }
        require(connection.responseCode == HttpURLConnection.HTTP_OK) {
            "Manifest request failed with HTTP ${connection.responseCode}"
        }
        val manifestBytes = connection.inputStream.use { it.readBounded(MAX_MANIFEST_BYTES) }
        val envelope = JSONObject(manifestBytes.toString(Charsets.UTF_8))
        require(envelope.getInt("envelope_format") == 1)
        require(envelope.getString("signature_algorithm") == "Ed25519")
        val payload = Base64.decode(envelope.getString("payload"), Base64.NO_WRAP)
        val signature = Base64.decode(envelope.getString("signature"), Base64.NO_WRAP)
        require(signature.size == 64 && PvmCrypto.verify(publicKeyPath, payload, signature)) {
            "Manifest signature verification failed"
        }
        val manifest = JSONObject(payload.toString(Charsets.UTF_8))
        require(manifest.getString("application_id") == applicationId)
        require(manifest.getString("channel") == channel)
        require(manifest.getString("profile") == profile)
        require(manifest.getString("platform") == "android")
        val release = manifest.getLong("release")
        val releaseFloor = maxOf(previous?.release ?: 0, minimumRelease)
        require(release >= releaseFloor) { "Manifest rejected by anti-rollback policy" }
        val digest = manifest.getString("sha256")
        require(SHA256.matches(digest)) { "Manifest contains an invalid SHA-256" }
        val size = manifest.getLong("size")
        require(size in 1..MAX_MODULE_BYTES) { "Module size is outside the host budget" }
        val destination = File(modules, "$digest.pvm")
        if (
            destination.isFile &&
            (destination.length() != size || !destination.hasSha256(digest))
        ) {
            require(destination.delete()) { "Cannot remove corrupt cached module" }
        }

        if (!destination.isFile) {
            val temporary = File(modules, "$digest.tmp")
            try {
                val moduleUri = server.resolve(manifest.getString("module_url"))
                require(
                    moduleUri.host == server.host &&
                        moduleUri.scheme == server.scheme &&
                        moduleUri.port == server.port &&
                        moduleUri.path == "/v1/modules/$digest.pvm"
                ) {
                    "Manifest module URL changed origin or hash binding"
                }
                val moduleConnection = open(moduleUri)
                moduleConnection.connect()
                require(moduleConnection.responseCode == HttpURLConnection.HTTP_OK) {
                    "Module request failed with HTTP ${moduleConnection.responseCode}"
                }
                val hash = MessageDigest.getInstance("SHA-256")
                var written = 0L
                FileOutputStream(temporary).use { output ->
                    moduleConnection.inputStream.use { input ->
                        val buffer = ByteArray(16_384)
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            written += count
                            require(written <= size) { "Module exceeds its declared size" }
                            hash.update(buffer, 0, count)
                            output.write(buffer, 0, count)
                        }
                    }
                    output.fd.sync()
                }
                require(written == size) { "Module download is truncated" }
                require(hash.digest().toHex() == digest) { "Module SHA-256 mismatch" }
                val validatedRelease =
                    PvmModuleValidator.validate(
                        temporary.absolutePath,
                        publicKeyPath,
                        applicationId,
                        channel,
                        profile,
                        releaseFloor,
                    )
                require(validatedRelease == release) { "Manifest/module release mismatch" }
                Os.rename(temporary.absolutePath, destination.absolutePath)
                Os.chmod(destination.absolutePath, 0b110000000)
            } finally {
                temporary.delete()
            }
        } else {
            val validatedRelease =
                PvmModuleValidator.validate(
                    destination.absolutePath,
                    publicKeyPath,
                    applicationId,
                    channel,
                    profile,
                    releaseFloor,
                )
            require(validatedRelease == release) { "Cached manifest/module release mismatch" }
        }

        val history =
            buildList {
                add(digest)
                previous?.history.orEmpty().filterTo(this) {
                    it != digest && File(modules, "$it.pvm").isFile
                }
            }.distinct().take(2)
        writeState(
            State(
                etag = connection.getHeaderField("ETag").orEmpty(),
                release = release,
                sha256 = digest,
                history = history,
            )
        )
        modules.listFiles { file -> file.extension == "pvm" }?.forEach {
            if (it.nameWithoutExtension !in history) it.delete()
        }
        return destination
    }

    private fun open(uri: URI): HttpURLConnection =
        (uri.toURL().openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            instanceFollowRedirects = false
            connectTimeout = 10_000
            readTimeout = 20_000
            activationToken?.let { setRequestProperty("Authorization", "Bearer $it") }
        }

    private fun readState(): State? =
        runCatching {
            require(currentFile.length() in 1..MAX_STATE_BYTES)
            val source = JSONObject(currentFile.readText())
            require(source.getInt("format") == 1)
            require(source.getString("application_id") == applicationId)
            require(source.getString("channel") == channel)
            require(source.getString("platform") == "android")
            require(source.getString("profile") == profile)
            val digest = source.getString("sha256")
            require(SHA256.matches(digest))
            val historyArray = source.getJSONArray("history")
            val history =
                buildList {
                    for (index in 0 until historyArray.length()) {
                        val value = historyArray.getString(index)
                        require(SHA256.matches(value))
                        add(value)
                    }
                }
            require(history.isNotEmpty() && history.size <= 2)
            require(history.first() == digest && history.distinct().size == history.size)
            val release = source.getLong("release")
            require(release > 0)
            State(
                etag = source.optString("etag"),
                release = release,
                sha256 = digest,
                history = history,
            )
        }.getOrNull()

    private fun writeState(state: State) {
        root.mkdirs()
        val temporary = File(root, "current.tmp")
        val json =
            JSONObject()
                .put("format", 1)
                .put("application_id", applicationId)
                .put("channel", channel)
                .put("platform", "android")
                .put("profile", profile)
                .put("etag", state.etag)
                .put("release", state.release)
                .put("sha256", state.sha256)
                .put("history", JSONArray(state.history))
                .toString()
        FileOutputStream(temporary).use {
            it.write(json.toByteArray())
            it.fd.sync()
        }
        Os.rename(temporary.absolutePath, currentFile.absolutePath)
        Os.chmod(currentFile.absolutePath, 0b110000000)
    }

    private data class State(
        val etag: String,
        val release: Long,
        val sha256: String,
        val history: List<String>,
    )

    companion object {
        private val SEGMENT = Regex("[A-Za-z0-9._-]{1,255}")
        private val SHA256 = Regex("[0-9a-f]{64}")
        private val PROFILES =
            setOf(
                "offline_sealed",
                "online_provisioned",
                "store_on_demand",
                "enterprise_managed",
            )
        private const val MAX_MANIFEST_BYTES = 64 * 1024
        private const val MAX_MODULE_BYTES = 16L * 1024L * 1024L
        private const val MAX_STATE_BYTES = 16L * 1024L
    }
}

private fun java.io.InputStream.readBounded(maximum: Int): ByteArray {
    val result = java.io.ByteArrayOutputStream()
    val buffer = ByteArray(8_192)
    while (true) {
        val count = read(buffer)
        if (count < 0) break
        require(result.size() + count <= maximum) { "Response exceeds its size budget" }
        result.write(buffer, 0, count)
    }
    return result.toByteArray()
}

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

private fun File.hasSha256(expected: String): Boolean =
    runCatching {
        val hash = MessageDigest.getInstance("SHA-256")
        inputStream().use { input ->
            val buffer = ByteArray(16_384)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                hash.update(buffer, 0, count)
            }
        }
        hash.digest().toHex() == expected
    }.getOrDefault(false)
