plugins {
    kotlin("multiplatform") version "2.4.10"
    `maven-publish`
}

group = "com.protectedvm"
version = "0.6.0"

kotlin {
    jvm()
    iosArm64()
    iosX64()
    iosSimulatorArm64()
    jvmToolchain(17)

    sourceSets {
        commonMain {
            kotlin.srcDir("../../../generated/host/kotlin")
        }
        commonTest.dependencies {
            implementation(kotlin("test"))
        }
    }
}

publishing {
    repositories {
        maven {
            name = "bundle"
            url = uri(layout.buildDirectory.dir("repository"))
        }
    }
}
