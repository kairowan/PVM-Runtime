// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "PVMRuntime",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "PVMRuntime", targets: ["PVMRuntime"]),
    ],
    targets: [
        .target(
            name: "PVMCore",
            path: "client",
            sources: [
                "src/runtime.cpp",
                "src/c_api.cpp",
            ],
            publicHeadersPath: "include",
            cxxSettings: [
                .define("PVM_USE_OPENSSL", to: "0"),
            ]
        ),
        .target(
            name: "PVMBridge",
            dependencies: ["PVMCore"],
            path: "client/platform/ios",
            sources: ["PVMRuntimeBridge.mm"],
            publicHeadersPath: "include"
        ),
        .target(
            name: "PVMRuntime",
            dependencies: ["PVMBridge"],
            path: "client/platform/ios/swift",
            resources: [
                .copy("PrivacyInfo.xcprivacy"),
            ]
        ),
    ],
    cxxLanguageStandard: .cxx17
)
