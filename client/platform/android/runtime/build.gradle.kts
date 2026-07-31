import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.library")
    `maven-publish`
}

android {
    namespace = "com.protectedvm.host"
    compileSdk = 36
    ndkVersion = "28.0.13004108"

    defaultConfig {
        minSdk = 24
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("../src/main/consumer-rules.pro")
        externalNativeBuild {
            cmake {
                cppFlags += "-std=c++17"
                abiFilters += listOf("arm64-v8a", "x86_64")
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("../CMakeLists.txt")
            version = "3.22.1"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    publishing {
        singleVariant("release")
    }
}

androidComponents {
    onVariants { variant ->
        variant.sources.kotlin?.addStaticSourceDirectory("../src/main/kotlin")
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    implementation("androidx.recyclerview:recyclerview:1.4.0")
    implementation("com.google.crypto.tink:tink-android:1.23.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
}

publishing {
    publications {
        register<MavenPublication>("release") {
            groupId = "com.protectedvm"
            artifactId = "pvm-runtime"
            version = "0.5.0"
            afterEvaluate {
                from(components["release"])
            }
            pom {
                name.set("PVM Runtime for Android")
                description.set("Precompiled Android host for the PVM C++17 runtime")
                url.set("https://github.com/kairowan/PVM-Runtime")
                licenses {
                    license {
                        name.set("Apache License, Version 2.0")
                        url.set("https://www.apache.org/licenses/LICENSE-2.0.txt")
                    }
                }
                scm {
                    url.set("https://github.com/kairowan/PVM-Runtime")
                    connection.set("scm:git:https://github.com/kairowan/PVM-Runtime.git")
                }
            }
        }
    }
    repositories {
        maven {
            name = "bundle"
            url = uri(layout.buildDirectory.dir("repository"))
        }
        val githubRepository = providers.environmentVariable("GITHUB_REPOSITORY")
        val githubToken = providers.environmentVariable("GITHUB_TOKEN")
        if (githubRepository.isPresent && githubToken.isPresent) {
            maven {
                name = "GitHubPackages"
                url = uri("https://maven.pkg.github.com/${githubRepository.get()}")
                credentials {
                    username =
                        providers.environmentVariable("GITHUB_ACTOR").orNull
                            ?: "github-actions"
                    password = githubToken.get()
                }
            }
        }
    }
}
