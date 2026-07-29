-keep class com.protectedvm.host.PvmRuntimeHost {
    *;
}

-keep class com.protectedvm.host.PvmModuleValidator {
    *;
}

-keep class com.protectedvm.host.PvmCrypto {
    public static boolean verify(java.lang.String, byte[], byte[]);
}
