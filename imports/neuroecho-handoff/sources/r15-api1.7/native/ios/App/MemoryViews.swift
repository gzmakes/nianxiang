import SwiftUI

struct MemoryListView: View {
    @EnvironmentObject private var store: EchoStore
    @State private var selected: EchoMemory?
    @State private var adding = false
    var body: some View {
        VStack(spacing:12) {
            Button { adding = true } label: { Label("手动记一件事",systemImage:"plus").frame(minHeight:44) }.disabled(store.busy || store.pending != nil)
            if (store.conversation?.memories ?? []).filter({$0.status != "deleted"}).isEmpty { Text("还没有记忆。你可以先说说话，需要记下时再决定。").foregroundStyle(EchoPalette.muted).echoCard() }
            ForEach((store.conversation?.memories ?? []).filter { $0.status != "deleted" }) { memory in
                Button { selected = memory } label: { VStack(alignment:.leading,spacing:12) { Text(memory.text).font(.body.weight(.semibold)); Text(memory.status == "confirmed" ? "你已确认；相关时可用于接续对话。" : "这是候选，尚未作为你确认过的事实。").font(.footnote).foregroundStyle(EchoPalette.muted); Text(memory.provenance).font(.caption).padding(.horizontal,10).padding(.vertical,6).overlay(RoundedRectangle(cornerRadius:12).stroke(EchoPalette.muted.opacity(0.5),style:StrokeStyle(lineWidth:1,dash:memory.kind == "inference" && memory.status != "confirmed" ? [4,3] : []))); Text("v\(memory.version) · 查看、纠正或忘掉").font(.caption).foregroundStyle(EchoPalette.muted) }.echoCard() }.buttonStyle(.plain)
            }
        }.sheet(item:$selected) { memory in NavigationStack { MemoryDetailView(memory:memory) } }
        .sheet(isPresented:$adding) { NavigationStack { NewMemoryView() } }
    }
}
struct MemoryDetailView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    let memory: EchoMemory
    @State private var text = ""
    @State private var revisions: [EchoRevision] = []
    @State private var error: String?
    @State private var busy = false
    @State private var forget = false
    @State private var expectedVersion: Int?
    @State private var conflict = false
    @State private var conflictSnapshotReady = false
    @State private var boundScope=""
    @State private var boundSID: String?
    private var belongsToCurrentIdentity: Bool {boundScope == store.scopeIdentity && boundSID == store.sessionID && boundSID != nil}
    private var latest: EchoMemory? { store.conversation?.memories.first(where:{$0.id == memory.id}) }
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:16) {
            Text(memory.provenance).font(.footnote).foregroundStyle(EchoPalette.muted)
            TextEditor(text:$text).frame(minHeight:150).padding(12).background(.white,in:RoundedRectangle(cornerRadius:18))
            VStack(alignment:.leading,spacing:10) { Text("说于：\(originalDate)"); Text("记下于：\(memory.createdAt ?? "时间未提供")"); Text(memory.status == "confirmed" ? "用在：相关对话的已确认记忆中。" : "用在：待核对内容，不作为你确认的事实。") }.font(.footnote).foregroundStyle(EchoPalette.muted).echoCard()
            if conflict {
                VStack(alignment:.leading,spacing:10) {
                    Text("这条记忆已在别处更新，你的修改还保留在上方。").font(.headline)
                    if conflictSnapshotReady, let latest { Text("当前 v\(latest.version)：\(latest.text)"); Button("我已核对，按这个版本继续编辑") { expectedVersion = latest.version; conflict = false; error = nil }.frame(minHeight:44) }
                    else if !conflictSnapshotReady { Text("最新版本暂未读到，先保留你的修改。"); Button("重新读取最新版本") { Task { await refreshConflict() } }.disabled(busy).frame(minHeight:44) }
                    else { Text("当前记录中没有找到这条记忆，请关闭后核对；不会新建或覆盖。") }
                }.echoCard()
            }
            Button("改一改这条") { Task { await update(confirm:false) } }.buttonStyle(EchoPrimaryButton()).disabled(busy || conflict || text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || text.unicodeScalars.count > 2000)
            if (latest ?? memory).status != "confirmed" { Button("是的，确认这条") { Task { await update(confirm:true) } }.frame(minHeight:44).disabled(busy || conflict) }
            Button("忘掉这条",role:.destructive) { forget = true }.frame(minHeight:44).disabled(busy || conflict)
            if let error { Text(error).font(.footnote).foregroundStyle(EchoPalette.muted) }
            if !revisions.isEmpty { Text("版本与来源").font(.headline); ForEach(revisions) { revision in VStack(alignment:.leading,spacing:6) { Text("v\(revision.version) · \(revision.createdAt ?? "时间未提供")").font(.caption).foregroundStyle(EchoPalette.muted); Text(revision.text); Text(revision.source).font(.footnote) }.echoCard() } }
        }.padding(20) }.disabled(!belongsToCurrentIdentity).background(EchoBackground()).navigationTitle("核对这条记忆").echoProtectingEdits().echoInlineNavigationTitle().toolbar { ToolbarItem(placement:.cancellationAction) { Button("关闭") { dismiss() } } }
        .onAppear {if boundScope.isEmpty {boundScope=store.scopeIdentity;boundSID=store.sessionID};if expectedVersion == nil {text=memory.text;expectedVersion=memory.version}}
        .task {let client=store.api,scope=store.scopeIdentity,sid=store.sessionID;do {let value=try await client.history(memoryID:memory.id);guard scope == store.scopeIdentity,sid == store.sessionID else {return};revisions=value} catch {if scope == store.scopeIdentity,sid == store.sessionID {self.error="历史暂时读不到：\(error.localizedDescription)"}}}
        .onChange(of:store.scopeIdentity) {_ in dismiss()}
        .onChange(of:store.sessionID) {_ in if !belongsToCurrentIdentity {dismiss()}}
        .confirmationDialog("忘掉这条记忆？",isPresented:$forget,titleVisibility:.visible) { Button("确认忘掉",role:.destructive) { Task { await delete() } }; Button("保留",role:.cancel) {} } message: { Text("这条记忆及相关派生内容停止用于回复；关联来源可能暂停，需要重新核对。与它无关的独立资料、原话和动作保留。") }
    }
    private var originalDate: String { guard let id = memory.sourceMessageId else { return "未提供原话时间" }; return store.conversation?.messages.first(where:{$0.id == id})?.createdAt ?? "未提供原话时间" }
    private func update(confirm: Bool) async {
        guard !busy,!conflict,belongsToCurrentIdentity else {return}
        let client=store.api
        busy = true;defer {busy = false}
        do {_ = try await client.updateMemory(id:memory.id,text:text == (latest ?? memory).text ? nil : text,confirm:confirm,expectedVersion:expectedVersion);guard belongsToCurrentIdentity else {return};try await store.refresh();guard belongsToCurrentIdentity else {return};dismiss()} catch {if belongsToCurrentIdentity {await handle(error)}}
    }
    private func delete() async {
        guard !busy,!conflict,belongsToCurrentIdentity else {return}
        let client=store.api
        busy = true;defer {busy = false}
        do {try await client.deleteMemory(id:memory.id,expectedVersion:expectedVersion);guard belongsToCurrentIdentity else {return};try await store.refresh();guard belongsToCurrentIdentity else {return};dismiss()} catch {if belongsToCurrentIdentity {await handle(error)}}
    }
    private func handle(_ failure: Error) async {
        if (failure as? EchoAPIError)?.statusCode == 409 {
            conflict = true; conflictSnapshotReady = false
            await refreshConflict()
        } else { error = "结果需要核对：\(failure.localizedDescription) 文字仍保留，不会自动重试。" }
    }
    private func refreshConflict() async {
        guard belongsToCurrentIdentity else {return}
        do {try await store.refresh();guard belongsToCurrentIdentity else {return};conflictSnapshotReady = true; error = "版本已变化，没有覆盖或自动重试。请先核对当前版本。" }
        catch {guard belongsToCurrentIdentity else {return};conflictSnapshotReady = false;self.error = "版本已变化，最新内容暂时读不到。你的修改保留，请稍后重新核对。" }
    }
}

struct NewMemoryView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var busy = false
    @State private var attempted = false
    @State private var error: String?
    let notice: String
    init(initialText: String = "", notice: String = "") { _text = State(initialValue:initialText); self.notice = notice }
    var body: some View {
        Form {
            if !notice.isEmpty { Text(notice).font(.footnote).foregroundStyle(EchoPalette.muted) }
            Section("我打算这样做") { Text("只把下方文字保存成待确认记忆，留在同一段对话。保存后还要由你确认，才作为你确认过的事实；不写入其他应用。"); TextEditor(text:$text).frame(minHeight:150); Text("1–2000字；不记也可以。").font(.footnote) }
            Button(busy ? "正在保存…" : "保存为待确认记忆") { Task { await save() } }.disabled(busy || attempted || store.pending != nil || text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || text.unicodeScalars.count > 2000)
            if let error { Text(error).font(.footnote) }
        }.navigationTitle("记一件事").echoProtectingEdits().toolbar { ToolbarItem(placement:.cancellationAction) { Button("不用") { dismiss() } } }
    }
    private func save() async {
        guard let sid = store.sessionID, !attempted else {return}
        let client=store.api,origin=store.scopeIdentity
        busy = true;attempted = true
        defer {busy = false}
        do {_ = try await client.addMemory(sessionID:sid,text:text); guard store.sessionID == sid,store.scopeIdentity == origin else {return};try await store.refresh();guard store.scopeIdentity == origin else {return};dismiss() }
        catch {guard store.scopeIdentity == origin else {return};self.error = "保存结果需要核对：\(error.localizedDescription) 请关闭后查看记忆列表；不会自动重复添加。" }
    }
}
