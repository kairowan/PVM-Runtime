package com.protectedvm.host

object PvmModuleValidator {
    fun validate(
        modulePath: String,
        publicKeyPath: String,
        applicationId: String,
        expectedChannel: String,
        expectedProfile: String,
        minimumRelease: Long,
    ): Long =
        nativeValidate(
            modulePath,
            publicKeyPath,
            applicationId,
            expectedChannel,
            expectedProfile,
            minimumRelease,
        )

    private external fun nativeValidate(
        modulePath: String,
        publicKeyPath: String,
        applicationId: String,
        expectedChannel: String,
        expectedProfile: String,
        minimumRelease: Long,
    ): Long

    init {
        System.loadLibrary("pvm_android")
    }
}
