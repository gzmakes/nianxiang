import SwiftUI

/// Small truthful status; neither push delivery nor cloud/offline merge.
struct ChangeRefreshNotice: View {
    @EnvironmentObject private var store: EchoStore
    var body: some View {
        if [.pending,.offline,.capabilitiesUnknown].contains(store.changeNoticeKind) {
            HStack(alignment:.center,spacing:10) {
                ChangeSyncStatusText().font(.footnote)
                Spacer(minLength:0)
                ChangeCheckButton().font(.footnote)
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
            if active,[.pending,.offline,.capabilitiesUnknown].contains(store.changeNoticeKind) {
                VStack(alignment:.leading,spacing:4) {
                    ChangeSyncStatusText()
                    Text("检查只读取状态；当前编辑保护仍保留。关闭此页后才安全更新内容，不会替换当前草稿。")
                    ChangeCheckButton()
                }.font(.footnote).padding(12).frame(maxWidth:.infinity,alignment:.leading).background(.regularMaterial)
            }
        }
        .onAppear {store.protectChangeReads(lease,active:active)}
        .onChange(of:active) {_,value in store.protectChangeReads(lease,active:value)}
        .onDisappear {store.protectChangeReads(lease,active:false)}
    }
}
struct ChangeCheckButton: View {
    @EnvironmentObject private var store: EchoStore
    var body: some View {Button(store.readingCapabilities ? "正在核对…" : EchoSharedReference.copy_connection_sync_check) {Task {await store.checkUpdatesExplicitly()}}.frame(minHeight:44).disabled(store.busy || store.verifyingDevice || store.readingCapabilities)}
}
struct ChangeSyncStatusText: View {
    @EnvironmentObject private var store: EchoStore
    var body: some View {
        switch store.changeNoticeKind {
        case .capabilitiesUnknown: Text("暂时没能读取服务能力，尚不能判断是否支持更新。草稿保留，可以重新检查。")
        case .offline: Text(EchoSharedReference.copy_connection_sync_offline)
        case .pending: Text(EchoSharedReference.copy_connection_sync_pending)
        case .unsupported: Text(EchoSharedReference.copy_connection_sync_unsupported)
        case .none:
            if store.capabilities == nil {Text("尚未读取服务能力，请连接后检查；这不代表服务不支持。")}
            else if store.changeSyncStatus == .updated {Text(EchoSharedReference.copy_connection_sync_updated)}
            else {Text("前台会定时只读检查；正在编辑或核对的原请求会保留。")}
        }
    }
}
extension View {
    func echoProtectingEdits(_ active: Bool = true) -> some View {modifier(ChangeReadProtection(active:active))}
}
