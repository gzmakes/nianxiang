import SwiftUI
import UniformTypeIdentifiers

private struct FileBatch: Identifiable { let id = UUID(); let files: [EchoSelectedFile] }
struct ConnectionsView: View {
    @EnvironmentObject private var store: EchoStore
    @State private var catalog: [EchoCatalogSource] = []
    @State private var error: String?
    @State private var importing = false
    @State private var batch: FileBatch?
    @State private var removing: EchoSource?
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:16) {
            Text("它能看的，由你选择").font(.title2.bold())
            Text(store.isRemote ? "默认不读取。所选文本先预览，由你确认后才接入同一段对话。" : "默认不读取。每次先说明范围，预览后才接入同一段对话。服务目前运行在 Mac，日历与代码库也指这台 Mac。").font(.footnote).foregroundStyle(EchoPalette.muted)
            ForEach(store.sources) { source in VStack(alignment:.leading,spacing:10) { Text(source.displayTitle).font(.headline); Text(source.stale == true ? "待核对 · 已暂停用于回复" : "你确认接入的只读快照").font(.footnote).foregroundStyle(EchoPalette.muted); Button("收回这份资料",role:.destructive) { removing = source }.frame(minHeight:44) }.echoCard() }
            Button { importing = true } label: { Label("选择这台设备上的文本文件",systemImage:"doc.badge.plus").frame(minHeight:44) }.echoCard().buttonStyle(.plain)
            if store.isRemote {Text("手机可预览并接入自己选择的文本文件，也可查看或收回已有资料。Mac CLI、日历和第三方账号读取请在电脑端操作；此处不会尝试。").font(.footnote).foregroundStyle(EchoPalette.muted)}
            ForEach(catalog.filter { $0.id != "local_files" }) { source in NavigationLink { SourceReaderView(source:source) } label: { VStack(alignment:.leading,spacing:8) { Text(source.name).font(.headline); Text(source.blurb).font(.footnote); Text(source.status == "ready" ? "可尝试只读 · 尚未接入" : source.hint ?? "连接前需要进一步配置").font(.caption).foregroundStyle(EchoPalette.muted) }.echoCard() }.buttonStyle(.plain) }
            VStack(alignment:.leading,spacing:8) { Text("Rokid 与脑电设备").font(.headline); Text("真机在队友处，尚待联调。此版本不连接眼镜、不读取手机传感器，也不会模拟设备已连通。").font(.footnote).foregroundStyle(EchoPalette.muted) }.echoCard()
            if let error { Text(error).font(.footnote).foregroundStyle(EchoPalette.muted) }
            Button("重新检查可用来源") { Task { await loadCatalog() } }.frame(minHeight:44)
        }.padding(20) }.background(EchoBackground()).navigationTitle("连接").echoInlineNavigationTitle().echoProtectingEdits(importing || batch != nil || removing != nil)
        .task(id:store.scopeIdentity) {await loadCatalog()}
        .onChange(of:store.scopeIdentity) {_ in catalog=[];removing=nil;batch=nil}
        .onChange(of:store.sessionID) {sid in if sid == nil {catalog=[];removing=nil;batch=nil}}
        .fileImporter(isPresented:$importing,allowedContentTypes:[.plainText,.json,.sourceCode,.commaSeparatedText],allowsMultipleSelection:true) { result in
            do {
                let urls = try result.get()
                guard (1...3).contains(urls.count) else { throw EchoAPIError.message("一次请选择 1–3 份文本文件。") }
                let files = try urls.map { url -> EchoSelectedFile in
                    let access = url.startAccessingSecurityScopedResource(); defer { if access { url.stopAccessingSecurityScopedResource() } }
                    let size = try url.resourceValues(forKeys:[.fileSizeKey]).fileSize ?? 0
                    guard size <= 256 * 1024 else { throw EchoAPIError.message("单个文件最多 256 KiB，请选择较小的文本文件。") }
                    let data = try Data(contentsOf:url)
                    guard data.count <= 256 * 1024, let text = String(data:data,encoding:.utf8) else { throw EchoAPIError.message("文件不是可读取的 UTF-8 文本。") }
                    return try EchoSelectedFile(name:url.lastPathComponent,text:text)
                }
                guard Set(files.map(\.name)).count == files.count else { throw EchoAPIError.message("文件重名，请分开选择，便于区分来源。") }
                batch = FileBatch(files:files)
            } catch { self.error = error.localizedDescription }
        }
        .sheet(item:$batch) { batch in NavigationStack { FileReviewView(files:batch.files) } }
        .confirmationDialog("收回「\(removing?.displayTitle ?? "这份资料")」？",isPresented:Binding(get:{removing != nil},set:{if !$0 {removing = nil}}),titleVisibility:.visible) {
            Button("收回并停止使用",role:.destructive) { guard let source = removing, let sid = store.sessionID else {return}; let client=store.api,scope=store.scopeIdentity;Task {do {try await client.revokeSource(id:source.id,sessionID:sid);guard store.scopeIdentity == scope,store.sessionID == sid else {return};try await store.refresh();guard store.scopeIdentity == scope else {return};removing=nil} catch {if store.scopeIdentity == scope,store.sessionID == sid {self.error="撤回结果需核对：\(error.localizedDescription)"}}} }
            Button("保留",role:.cancel) { removing = nil }
        } message: { Text("这份资料及其派生理解会停止使用，其他来源、手动记忆和聊天文字保留。第三方账号授权不会被撤销。\n" + EchoSharedReference.copy_companion_boundary_effect) }
    }
    private func loadCatalog() async {
        guard !store.isRemote else {catalog=[];error=nil;return}
        let client=store.api,scope=store.scopeIdentity
        do {let value=try await client.sources();guard scope == store.scopeIdentity else {return};catalog=value;error=nil}
        catch {if scope == store.scopeIdentity {self.error=error.localizedDescription}}
    }
}
struct FileReviewView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    let files: [EchoSelectedFile]
    @State private var busy = false
    @State private var attempted = false
    @State private var error: String?
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:16) {
            Text("我打算这样做").font(.title2.bold())
            Text("1 只接入下面 \(files.count) 份文件的前 4000 个 Unicode 字符。\n2 保存在回响服务中，用于这段对话。\n3 不读取其他文件；不修改原文件。").font(.body)
            Text("之后聊天时，必要摘要和检索片段可能发送给当前模型服务。你可以在连接页逐份收回。").font(.footnote).foregroundStyle(EchoPalette.muted)
            ForEach(files) { file in VStack(alignment:.leading,spacing:8) { Text(file.name).font(.headline); Text(file.text).font(.body).textSelection(.enabled) }.echoCard() }
            Button(busy ? "正在接入…" : "好，接入这些文字") { Task { await confirm() } }.buttonStyle(EchoPrimaryButton()).disabled(busy || attempted || store.pending != nil)
            if store.pending != nil { Text("请先核对当前聊天的发送状态，再接入资料。").font(.footnote) }
            if let error { Text(error).font(.footnote) }
        }.padding(20) }.background(EchoBackground()).navigationTitle("先预览，再确认").echoProtectingEdits().toolbar { ToolbarItem(placement:.cancellationAction) { Button("不用") { dismiss() } } }
    }
    private func confirm() async {
        guard let sid = store.sessionID, !attempted else { return };let scope=store.scopeIdentity,client=store.api;attempted = true; busy = true
        defer {busy = false}
        do { let result = try await client.attachFiles(files,sessionID:sid);guard store.scopeIdentity == scope else {return};try store.accept(result,expectedID:sid); dismiss() }
        catch { self.error = "接入结果未确认：\(error.localizedDescription) 请返回连接页核对；不会自动重复接入。" }
    }
}
struct SourceReaderView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    let source: EchoCatalogSource
    @State private var target = ""
    @State private var preview: EchoPreview?
    @State private var busy = false
    @State private var attempted = false
    @State private var error: String?
    @State private var request = UUID()
    private var supported: Bool { !store.isRemote && ["feishu","notion","git","github","apple_calendar","apple_reminders"].contains(source.id) && store.capabilities?.platformStatus[source.id] != "platform_unsupported" }
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:16) {
            Text("我打算这样做").font(.title2.bold())
            Text("只读范围：\((source.reads ?? [source.blurb]).joined(separator:"、"))。先在当前页面预览，再由你确认接入。").echoCard()
            if ["apple_calendar","apple_reminders","git"].contains(source.id) { Text("读取的是运行回响服务的 Mac，不是这部 iPhone。系统权限也在 Mac 上确认。").font(.footnote).foregroundStyle(EchoPalette.muted) }
            if source.id == "feishu" { TextField("指定一篇飞书文档的完整链接",text:$target).echoURLInput().textFieldStyle(.roundedBorder); Text("使用 Mac 服务已有的飞书授权；此处不发起账号登录。会读取整篇，提取后最多保留12000字，并在确认前展示完整保留内容。").font(.footnote) }
            if source.id == "notion" { TextField("指定一个 Notion 页面链接",text:$target).echoURLInput().textFieldStyle(.roundedBorder); Text("仅使用 Mac 已登录的官方 ntn CLI，只读该页前50个顶层文本块；未登录会如实报错。").font(.footnote) }
            if source.id == "git" { TextField("Mac 上代码库的完整目录",text:$target).echoURLInput().textFieldStyle(.roundedBorder) }
            if supported { Button("同意这个范围，读取预览") { Task { await readPreview() } }.buttonStyle(EchoPrimaryButton()).disabled(busy || store.pending != nil) }
            else if store.isRemote {Text("这项电脑本机读取不向设备连接开放，请在电脑上连接。手机可查看或收回已接入资料。").echoCard()}
            else { Text("此原生端暂未实现该来源的凭据输入。\(source.hint ?? "请先在 Mac 上配置。") 当前没有读取或接入。").font(.body).echoCard() }
            if let preview {
                VStack(alignment:.leading,spacing:12) {
                    Text(preview.title ?? source.name).font(.headline)
                    if let text = preview.preview {
                        if source.id == "feishu", let scope = preview.feishuPreviewScope { Text(scope).font(.caption).foregroundStyle(EchoPalette.muted) }
                        Text(text).textSelection(.enabled)
                    }
                    ForEach(Array((preview.items ?? []).enumerated()),id:\.offset) { _, item in Text(item.title + (item.summary.map { " · " + $0 } ?? "")).textSelection(.enabled) }
                    if let understanding = preview.understanding {
                        PreviewUnderstanding(title:"资料事实",lines:understanding.facts ?? [])
                        PreviewUnderstanding(title:"推测 · 待确认",lines:understanding.inferences ?? [])
                        PreviewUnderstanding(title:"想问你",lines:understanding.questions ?? [])
                    }
                    Text("确认后保存到同一段对话。生成理解或之后聊天时，必要内容可能发送给当前模型服务。不会修改第三方资料。预览10分钟有效，仅能确认一次。").font(.footnote).foregroundStyle(EchoPalette.muted)
                    Button("确认接入当前对话") { Task { await attach() } }.buttonStyle(EchoPrimaryButton()).disabled(busy || attempted || store.pending != nil || (try? preview.requireID(for:source.id)) == nil)
                }.echoCard()
            }
            if busy { ProgressView("正在处理…") }
            if let error { Text(error).font(.footnote).foregroundStyle(EchoPalette.muted) }
        }.padding(20) }.background(EchoBackground()).navigationTitle(source.name).echoProtectingEdits().echoInlineNavigationTitle()
        .onChange(of:target) { _, _ in request = UUID(); preview = nil; attempted = false; busy = false; error = nil }
        .onDisappear { request = UUID() }
    }
    private func readPreview() async {
        guard let sid = store.sessionID else { return }; let current = UUID(); request = current
        let origin = store.scopeIdentity, text = target, client = store.api
        busy = true; error = nil; preview = nil; attempted = false
        defer { if request == current {busy = false} }
        do { let value = try await client.previewSource(source.id,target:text); _ = try value.requireID(for:source.id); guard request == current, store.sessionID == sid, store.scopeIdentity == origin else {return}; preview = value }
        catch { if request == current {self.error = error.localizedDescription} }
    }
    private func attach() async {
        guard let preview, let id = try? preview.requireID(for:source.id), let sid = store.sessionID, !attempted else {return}
        let current = request, origin = store.scopeIdentity, client = store.api
        busy = true; attempted = true
        defer {busy = false}
        do { let value = try await client.attachSource(source.id,target:target,previewID:id,sessionID:sid); guard request == current, store.scopeIdentity == origin else {return}; try store.accept(value,expectedID:sid); dismiss() }
        catch { if request == current {self.error = "接入结果需核对：\(error.localizedDescription) 请返回资料列表查看；不会自动重复确认。"} }
    }
}
private struct PreviewUnderstanding: View {
    let title: String
    let lines: [String]
    var body: some View { if !lines.isEmpty { VStack(alignment:.leading,spacing:8) { Text(title).font(.headline); ForEach(Array(lines.enumerated()),id:\.offset) { _, line in Text(line).font(.body) } } } }
}
