import SwiftUI

/// Small truthful status; neither push delivery nor cloud/offline merge.
struct ChangeRefreshNotice: View {
    @EnvironmentObject private var store: EchoStore
    var body: some View {
        if store.changeSyncStatus == .pending || store.changeSyncStatus == .offline {
            HStack(alignment:.center,spacing:10) {
                Text(store.changeSyncStatus == .pending ? EchoSharedReference.copy_connection_sync_pending : EchoSharedReference.copy_connection_sync_offline).font(.footnote)
                Spacer(minLength:0)
                Button(EchoSharedReference.copy_connection_sync_check) {Task {await store.refreshFromForeground()}}.font(.footnote).frame(minHeight:44)
            }.padding(.horizontal,16).echoGlass().padding(.horizontal,20)
        }
    }
}
private struct ChangeReadProtection: ViewModifier {
    @EnvironmentObject private var store: EchoStore
    @State private var lease=UUID()
    let active: Bool
    func body(content: Content) -> some View {
        content.safeAreaInset(edge:.top,spacing:4) {
            if active,store.changesWaiting {Text(EchoSharedReference.copy_connection_sync_pending + " 关闭此页后会安全检查；不会替换当前草稿。").font(.footnote).padding(12).frame(maxWidth:.infinity,alignment:.leading).background(.regularMaterial)}
        }
        .onAppear {store.protectChangeReads(lease,active:active)}
        .onChange(of:active) {_,value in store.protectChangeReads(lease,active:value)}
        .onDisappear {store.protectChangeReads(lease,active:false)}
    }
}
extension View {
    func echoProtectingEdits(_ active: Bool = true) -> some View {modifier(ChangeReadProtection(active:active))}
}
