// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "EchoCore", platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "EchoCore", targets: ["EchoCore"]), .executable(name:"EchoCoreChecks",targets:["EchoCoreChecks"])],
    targets: [.target(name: "EchoCore"), .executableTarget(name:"EchoCoreChecks",dependencies:["EchoCore"],path:"Checks")])
