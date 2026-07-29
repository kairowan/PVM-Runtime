import org.gradle.api.tasks.Sync
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val repositoryRoot = rootProject.layout.projectDirectory.dir("../../..")
val deliveryRoot = repositoryRoot.dir("build/delivery/client/android/offline_sealed")

val generatePvmDelivery by tasks.registering(Exec::class) {
    workingDir(repositoryRoot)
    commandLine("make", "delivery-matrix")
}

val syncPvmAssets by tasks.registering(Sync::class) {
    dependsOn(generatePvmDelivery)
    from(deliveryRoot) {
        include("bootstrap.json", "module-public-key.pem", "module.pvm")
    }
    into(layout.buildDirectory.dir("generated/pvmAssets"))
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

    buildTypes {
        create("minified") {
            initWith(getByName("release"))
            matchingFallbacks += listOf("release")
            signingConfig = signingConfigs.getByName("debug")
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }

    sourceSets.named("main") {
        assets.srcDir(layout.buildDirectory.dir("generated/pvmAssets"))
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
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
