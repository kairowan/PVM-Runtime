package com.protectedvm.host

object PvmModuleValidator {
    fun validate(
        modulePath: String,
        publicKeyPath: String,
        applicationId: String,
        minimumRelease: Long,
    ): Long = nativeValidate(modulePath, publicKeyPath, applicationId, minimumRelease)

    private external fun nativeValidate(
        modulePath: String,
        publicKeyPath: String,
        applicationId: String,
        minimumRelease: Long,
    ): Long

    init {
        System.loadLibrary("pvm_android")
    }
}
