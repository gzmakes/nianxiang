import SwiftUI

@main @MainActor struct EchoApp: App {
    @StateObject private var store = EchoStore()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup { NavigationStack { EchoRootView() }.environmentObject(store).preferredColorScheme(.light)
            .onChange(of:scenePhase) {_,phase in store.setChangeMonitoringActive(phase == .active);if phase == .active {Task {await store.refreshFromForeground()}}}
        }
    }
}
