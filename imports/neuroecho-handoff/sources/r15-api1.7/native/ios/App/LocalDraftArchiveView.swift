import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

struct LocalDraftArchiveView: View {
    @EnvironmentObject private var store: EchoStore
    let profile: EchoDeviceProfile
    @State private var archive: EchoLocalDraftArchive?
    @State private var copiedID: String?
    var body: some View {
        ScrollView {VStack(alignment:.leading,spacing:16) {
            Text("原连接的本机草稿").font(.title2.bold())
            Text(profile.label).font(.headline)
            Text(profile.origin).font(.footnote).textSelection(.enabled)
            Text("只查看这份原连接留在本机的文字，不连接服务、不读取令牌、不迁移到当前身份。复制后也不会自动发送。未决操作可能已经处理；这里不代表已取消或撤回。").font(.footnote).echoCard()
            if let archive {
                if archive.entries.isEmpty {Text("未找到可显示的本机草稿文字。没有联网核对，也没有删除记录。").echoCard()}
                ForEach(archive.entries) {entry in
                    VStack(alignment:.leading,spacing:12) {
                        Text(entry.title).font(.headline)
                        Text(entry.text).textSelection(.enabled)
                        Text(entry.detail).font(.footnote).foregroundStyle(EchoPalette.muted)
                        Button(copiedID == entry.id ? "已复制文字" : "复制这份文字") {copy(entry.text);copiedID=entry.id}.frame(minHeight:44)
                    }.echoCard()
                }
                if archive.unreadableCount > 0 {Text("有 \(archive.unreadableCount) 份本机记录暂时无法安全读取，原数据保留；没有尝试补造或恢复请求。").font(.footnote)}
            } else {Text("这份连接不在本应用保存的身份中，未读取任何草稿。").font(.footnote)}
        }.padding(20)}.background(EchoBackground()).navigationTitle("本机草稿副本").echoInlineNavigationTitle().echoProtectingEdits()
        .onAppear {archive=store.localDraftArchive(for:profile)}
    }
    private func copy(_ text: String) {
        #if canImport(UIKit)
        UIPasteboard.general.string=text
        #elseif canImport(AppKit)
        NSPasteboard.general.clearContents();NSPasteboard.general.setString(text,forType:.string)
        #endif
    }
}
