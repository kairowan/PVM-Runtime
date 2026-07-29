package com.protectedvm.host

import android.util.Base64
import android.os.Build
import java.io.File
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.X509EncodedKeySpec

fun interface PvmSignatureVerifier {
    fun verify(publicKeyPath: String, payload: ByteArray, signature: ByteArray): Boolean
}

object PvmCrypto {
    @Volatile
    private var installed: PvmSignatureVerifier? = null

    /**
     * Required on Android API 24–32. Install the app's already-audited Ed25519 provider before
     * creating a PvmRuntimeHost; API 33+ uses the platform JCA provider by default.
     */
    @Synchronized
    fun installVerifier(verifier: PvmSignatureVerifier) {
        check(installed == null) { "PVM signature verifier is already installed" }
        installed = verifier
    }

    @JvmStatic
    fun verify(publicKeyPath: String, payload: ByteArray, signature: ByteArray): Boolean {
        installed?.let { return it.verify(publicKeyPath, payload, signature) }
        if (Build.VERSION.SDK_INT < 33) return false
        return runCatching {
                require(signature.size == 64)
                val pem =
                    File(publicKeyPath)
                        .readLines()
                        .filterNot { it.startsWith("-----") }
                        .joinToString("")
                val publicKey =
                    KeyFactory.getInstance("Ed25519")
                        .generatePublic(X509EncodedKeySpec(Base64.decode(pem, Base64.DEFAULT)))
                Signature.getInstance("Ed25519").run {
                    initVerify(publicKey)
                    update(payload)
                    verify(signature)
                }
            }
            .getOrDefault(false)
    }
}
