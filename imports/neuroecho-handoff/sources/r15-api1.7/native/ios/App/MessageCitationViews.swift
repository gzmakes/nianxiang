import SwiftUI

struct MessageCitationLinks: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase
    let message: EchoMessage
    let scope: String
    let sessionID: String?
    @State private var error: String?
    var body: some View {
        if !message.documentCitations.isEmpty {
            VStack(alignment:.leading,spacing:4) {
                ForEach(Array(message.documentCitations.enumerated()),id:\.offset) { _, document in
                    Button { open(document) } label: {
                        Label { Text("查阅 · " + document.title).lineLimit(2) } icon: {Image(systemName:"doc.text")}
                            .font(.footnote).frame(minHeight:44,alignment:.leading)
                    }.accessibilityLabel("打开飞书文档：" + document.title)
                }
                Text("文档权限与飞书连接在电脑端管理。").font(.caption).foregroundStyle(EchoPalette.muted)
                if let error {Text(error).font(.caption).foregroundStyle(EchoPalette.muted)}
            }.frame(maxWidth:310,alignment:.leading)
        }
    }
    private func open(_ document: EchoFeishuDocumentCitation) {
        guard scenePhase == .active,
              let target = EchoDocumentCitationTarget(message:message,document:document,origin:scope,sessionID:sessionID),
              let url = target.resolvedURL(origin:store.scopeIdentity,sessionID:store.sessionID,messages:store.visibleMessages) else {
            error="这条来源已变化，请先核对当前回复。"; return
        }
        error=nil
        // The system opens the document; no service bearer, account login or fetch is sent here.
        openURL(url) { accepted in
            guard store.scopeIdentity == scope, store.sessionID == sessionID,
                  target.resolvedURL(origin:store.scopeIdentity,sessionID:store.sessionID,messages:store.visibleMessages) == url else {return}
            if !accepted {error="暂时无法打开文档，请回电脑核对飞书连接。"}
        }
    }
}
