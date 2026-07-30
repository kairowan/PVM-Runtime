import org.gradle.api.tasks.Sync
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
}

val repositoryRoot = rootProject.layout.projectDirectory.dir("../../..")
val deliveryRoot = repositoryRoot.dir("build/delivery/client/android/offline_sealed")
val pvmAssetsDirectory =
    objects.directoryProperty().convention(layout.buildDirectory.dir("generated/pvmAssets"))
val releaseStore = providers.environmentVariable("PVM_ANDROID_KEYSTORE").orNull
val releaseStorePassword = providers.environmentVariable("PVM_ANDROID_STORE_PASSWORD").orNull
val releaseKeyAlias = providers.environmentVariable("PVM_ANDROID_KEY_ALIAS").orNull
val releaseKeyPassword = providers.environmentVariable("PVM_ANDROID_KEY_PASSWORD").orNull
val hasReleaseSigning =
    listOf(releaseStore, releaseStorePassword, releaseKeyAlias, releaseKeyPassword).all {
        !it.isNullOrBlank()
    }

val generatePvmDelivery by tasks.registering(Exec::class) {
    workingDir(repositoryRoot)
    commandLine("make", "delivery-matrix")
}

val syncPvmAssets by tasks.registering(Sync::class) {
    dependsOn(generatePvmDelivery)
    from(deliveryRoot) {
        include("bootstrap.json", "module-public-key.pem", "module.pvm")
    }
    into(pvmAssetsDirectory)
}

android {
    namespace = "com.protectedvm.demo"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.example.protected"
        minSdk = 33
        targetSdk = 36
        versionCode = 5
        versionName = "0.5.0"
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("production") {
                storeFile = file(requireNotNull(releaseStore))
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
                enableV1Signing = false
                enableV2Signing = true
                enableV3Signing = true
                enableV4Signing = true
            }
        }
    }

    buildTypes {
        getByName("release") {
            if (hasReleaseSigning) signingConfig = signingConfigs.getByName("production")
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
        create("minified") {
            initWith(getByName("release"))
            matchingFallbacks += listOf("release")
            signingConfig = signingConfigs.getByName("debug")
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(syncPvmAssets) {
            pvmAssetsDirectory
        }
    }
}

val verifyProductionSigning by tasks.registering {
    doLast {
        require(hasReleaseSigning) {
            "Set PVM_ANDROID_KEYSTORE, PVM_ANDROID_STORE_PASSWORD, " +
                "PVM_ANDROID_KEY_ALIAS and PVM_ANDROID_KEY_PASSWORD"
        }
        require(file(requireNotNull(releaseStore)).isFile) {
            "PVM_ANDROID_KEYSTORE does not name a readable file"
        }
    }
}

tasks.matching { it.name == "assembleRelease" || it.name == "bundleRelease" }.configureEach {
    dependsOn(verifyProductionSigning)
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

tasks.named("preBuild").configure {
    dependsOn(syncPvmAssets)
}

dependencies {
    implementation(project(":runtime"))
}
