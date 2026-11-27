// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Nexxvis",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "Nexxvis",
            path: "Sources/Nexxvis",
            linkerSettings: [
                .linkedFramework("AppKit"),
                .linkedFramework("OpenGL"),
                .linkedFramework("Accelerate"),
                .linkedFramework("ScreenCaptureKit"),
                .linkedFramework("CoreMedia"),
                .linkedFramework("CoreVideo"),
                .linkedFramework("ImageIO"),
                .linkedFramework("UniformTypeIdentifiers"),
            ]
        )
    ],
    swiftLanguageVersions: [.v5]
)
