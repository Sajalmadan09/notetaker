// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "NotetakerHelper",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "NotetakerHelper", path: "Sources/NotetakerHelper")
    ]
)
