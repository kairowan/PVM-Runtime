package com.protectedvm.host

import android.util.Base64
import android.util.Log
import com.google.crypto.tink.subtle.Ed25519Verify
import java.io.File

fun interface PvmSignatureVerifier {
    fun verify(publicKeyPath: String, payload: ByteArray, signature: ByteArray): Boolean
}

object PvmCrypto {
    @Volatile
    private var installed: PvmSignatureVerifier? = null

    @Volatile
    var lastFailure: String? = null
        private set

    /**
     * Replaces the bundled Tink verifier when the host app already has an audited Ed25519
     * implementation.
     */
    @Synchronized
    fun installVerifier(verifier: PvmSignatureVerifier) {
        check(installed == null) { "PVM signature verifier is already installed" }
        installed = verifier
    }

    @JvmStatic
    fun verify(publicKeyPath: String, payload: ByteArray, signature: ByteArray): Boolean {
        installed?.let {
            return it.verify(publicKeyPath, payload, signature).also { verified ->
                lastFailure = if (verified) null else "Installed Ed25519 verifier rejected the signature"
            }
        }
        return runCatching {
                require(signature.size == 64)
                val pem =
                    File(publicKeyPath)
                        .readLines()
                        .filterNot { it.startsWith("-----") }
                        .joinToString("")
                val encoded = Base64.decode(pem, Base64.DEFAULT)
                require(
                    encoded.size == X509_PREFIX.size + Ed25519Verify.PUBLIC_KEY_LEN &&
                        encoded.copyOfRange(0, X509_PREFIX.size).contentEquals(X509_PREFIX),
                ) { "Public key is not an Ed25519 SubjectPublicKeyInfo value" }
                val rawKey = encoded.copyOfRange(X509_PREFIX.size, encoded.size)
                Ed25519Verify(rawKey).verify(signature, payload)
                lastFailure = null
                true
            }
            .onFailure {
                lastFailure = it.message ?: it.javaClass.simpleName
                Log.e("ProtectedVM", "Ed25519 verification failed", it)
            }
            .getOrDefault(false)
    }

    private val X509_PREFIX =
        byteArrayOf(
            0x30,
            0x2a,
            0x30,
            0x05,
            0x06,
            0x03,
            0x2b,
            0x65,
            0x70,
            0x03,
            0x21,
            0x00,
        )
}
