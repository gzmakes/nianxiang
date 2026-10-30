import SwiftUI

private struct ActionSeed: Identifiable { let id = UUID(); let kind: String; let existing: EchoAction? }
struct ActionsView: View {
    @EnvironmentObject private var store: EchoStore
    @State private var seed: ActionSeed?
    @State private var error: String?
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:16) {
            Text("先看清，再开始").font(.title2.bold())
            NavigationLink("查看与安排应用内跟进") { FollowupsView() }.frame(minHeight:44)
            Text("这里只保存回响服务中的任务与草稿；不发送消息，不写入 iPhone 或 Mac 的日历、提醒事项。").font(.footnote).foregroundStyle(EchoPalette.muted)
            if !store.isRemote {HStack { ForEach([("message","消息草稿"),("reminder","提醒"),("calendar","日历安排")],id:\.0) { kind, title in Button(title) { seed = ActionSeed(kind:kind,existing:nil) }.frame(minHeight:44) } }}
            else {Text("设备连接不开放电脑本机动作与草稿执行，请使用应用内跟进；不会写入系统或调用 CLI。").font(.footnote)}
            if store.actions.isEmpty { Text(store.isRemote ? "设备连接只查看应用内跟进；电脑动作不在此开放。" : "还没有保存的动作，可以自己写一条。").echoCard() }
            ForEach(store.actions) { action in VStack(alignment:.leading,spacing:10) {
                Text(action.title).font(.headline); Text(action.statusLabel).font(.footnote).foregroundStyle(EchoPalette.muted)
                if let when = action.whenText, !when.isEmpty { Text(when).font(.footnote) }
                if let detail = action.detail, !detail.isEmpty { Text(detail).textSelection(.enabled) }
                if !store.isRemote,action.status == "previewed" { Button("继续确认原预览") { seed = ActionSeed(kind:action.kind,existing:action) }.frame(minHeight:44) }
                if !store.isRemote,["unknown","executing"].contains(action.status) { Button("只核对本机记录") { Task { await check(action) } }.frame(minHeight:44) }
            }.echoCard() }
            if let error { Text(error).font(.footnote) }
            Button("重新读取记录") { Task { await refresh() } }.frame(minHeight:44)
        }.padding(20) }.background(EchoBackground()).navigationTitle("任务与草稿").echoInlineNavigationTitle()
        .task { await refresh() }.sheet(item:$seed) { seed in NavigationStack { ActionComposerView(kind:seed.kind,existing:seed.existing) } }
    }
    private func refresh() async { do { try await store.refresh(); error = nil } catch { self.error = error.localizedDescription } }
    private func check(_ action: EchoAction) async {
        guard let sid=store.sessionID,!store.isRemote else {return}
        let client=store.api,scope=store.scopeIdentity
        do {let list=try await client.actions(sessionID:sid);guard store.scopeIdentity == scope,store.sessionID == sid else {return}; store.actions = list
            let latest = list.first {$0.id == action.id}; error = latest.map { ["unknown","executing"].contains($0.status) ? "本机记录仍未确认。请在 Mac 对应系统中核对；这里不会再次写入。" : "已刷新这条记录的状态。" } ?? "没有找到这条记录，请核对服务地址。"
        } catch { self.error = error.localizedDescription }
    }
}
struct ActionComposerView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    let kind: String
    let existing: EchoAction?
    @State private var title = ""
    @State private var detail = ""
    @State private var date = Date().addingTimeInterval(86400)
    @State private var existingID: String?
    @State private var busy = false
    @State private var attempted = false
    @State private var error: String?
    @State private var token = UUID()
    var body: some View {
        Form {
            Section("我打算这样做") { Text(existing == nil ? "1 保存你核对的标题、正文与时间。\n2 只存回响服务，不发送，也不写入任何系统日历或提醒。\n3 你现在可以修改或取消。" : "使用已保存的同一条预览与原内容；确认前先核对状态，不新建第二条。") }
            Section("先核对内容") { TextField("标题",text:$title).disabled(existing != nil); TextEditor(text:$detail).frame(minHeight:140).disabled(existing != nil)
                if kind == "calendar" { if let existing { Text(existing.whenText?.isEmpty == false ? existing.whenText! : "未设时间，只保存本机记录") } else { DatePicker("时间",selection:$date,displayedComponents:[.date,.hourAndMinute]) } }
            }
            Section { Button(busy ? "正在核对并保存…" : "好，保存到回响服务") { Task { await confirm() } }.disabled(busy || attempted || title.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || (kind == "message" && detail.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty))
                if let error { Text(error).font(.footnote) }
                Text("不会通知你，不会替你发送消息。需要实际发送或通知时仍由你在对应应用完成。").font(.footnote).foregroundStyle(EchoPalette.muted)
            }
        }.navigationTitle(kind == "message" ? "消息草稿" : kind == "calendar" ? "日历安排" : "提醒草稿").echoProtectingEdits().echoInlineNavigationTitle().toolbar { ToolbarItem(placement:.cancellationAction) { Button("不用") { token = UUID(); dismiss() } } }
        .onAppear { title = existing?.title ?? ""; detail = existing?.detail ?? ""; existingID = existing?.id }
        .onDisappear { token = UUID() }
    }
    private func confirm() async {
        guard !store.isRemote else {error="设备连接不开放电脑本机动作。";return}
        guard let sid = store.sessionID, !attempted, title.count <= 200, detail.unicodeScalars.count <= 2000 else { error = "标题最多200字，正文最多2000字；文字仍保留。"; return }
        let current = token, origin = store.scopeIdentity, client = store.api
        busy = true; attempted = true
        defer { busy = false }
        do {
            if let id = existingID {
                _ = try await client.requirePreviewedAction(id:id,sessionID:sid)
                guard token == current, store.sessionID == sid, store.scopeIdentity == origin else {return}
            } else {
                let formatter = ISO8601DateFormatter(); formatter.timeZone = .current
                let preview = try await client.createAction(sessionID:sid,kind:kind,title:title,detail:detail,when:kind == "calendar" ? formatter.string(from:date) : "")
                existingID = preview.id
            }
            guard token == current, store.sessionID == sid, store.scopeIdentity == origin, let id = existingID else {return}
            let done = try await client.commitAction(id:id)
            guard token == current, store.sessionID == sid else {return}
            guard done.status == "committed" else { throw EchoAPIError.message("结果尚未确认，请回到任务列表只核对记录，不要重复新建。") }
            try await store.refresh(); dismiss()
        } catch { if token == current {self.error = "保存结果需核对：\(error.localizedDescription) 请关闭此页并查看任务列表；不会自动重建或重试。"} }
    }
}

/// A follow-up is a record shown when the app is opened; it is not a system notification.
struct FollowupsView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var records: [EchoFollowup] = []
    @State private var loading = false
    @State private var loadVersion = UUID()
    @State private var updatingID: String?
    @State private var error: String?
    @State private var composer = false
    @State private var receipt: String?
    @State private var cancelling: EchoFollowup?
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:16) {
            Text("约好下次再聊").font(.title2.bold())
            Text("到约定时间后，打开回响才会看到；不会推送通知，也不会在后台主动联系你。")
                .font(.footnote).foregroundStyle(EchoPalette.muted)
            if let pending = store.pendingFollowup {
                VStack(alignment:.leading,spacing:10) {
                    Text("上次的保存仍需核对").font(.headline)
                    Text(pending.content).textSelection(.enabled)
                    Text("原时间：\(displayDate(pending.dueAt,timeZone:pending.timeZone))。请求保存在本机；核对前不能新建。")
                        .font(.footnote).foregroundStyle(EchoPalette.muted)
                    Button("刷新并核对记录") { Task { await store.refreshFollowups(); await refresh() } }.frame(minHeight:44)
                    Button("重试原请求") { Task { await store.retryFollowup(); await refresh() } }.frame(minHeight:44).disabled(store.busy)
                }.echoCard()
            } else {
                Button(store.followupDraft == nil && store.followupForm == nil ? "安排下次跟进" : "继续跟进草稿") { composer = true }.buttonStyle(EchoPrimaryButton()).disabled(store.busy || store.capabilities?.features["in_app_one_time_followups"] != true)
                if store.capabilities?.features["in_app_one_time_followups"] != true {Text("当前服务尚未声明应用内跟进能力，请核对服务版本。").font(.footnote)}
            }
            if let notice = store.followupNotice { Text(notice).font(.footnote).foregroundStyle(EchoPalette.muted) }
            if let error { Text(error).foregroundStyle(EchoPalette.muted).textSelection(.enabled) }
            if let receipt {Text(receipt).font(.footnote).foregroundStyle(EchoPalette.muted)}
            if loading && records.isEmpty { ProgressView("正在读取跟进") }
            else if records.isEmpty && error == nil { Text("还没有约好的跟进。").echoCard() }
            ForEach(records) { item in
                VStack(alignment:.leading,spacing:10) {
                    Text(item.content).font(.headline).textSelection(.enabled)
                    Text("\(label(item)) · \(displayDate(item.dueAt,timeZone:item.timeZone))").font(.footnote).foregroundStyle(EchoPalette.muted)
                    Text("来源：你在回响中确认的跟进安排").font(.caption).foregroundStyle(EchoPalette.muted)
                    Text(item.allowContact == true ? "保存过轻问约定；是否仍有效以下方许可为准。当前iOS不自动轻问或通知。" : "未同意主动联系，仅作为待办查看。").font(.footnote).foregroundStyle(EchoPalette.muted)
                    if item.allowContact == true {Text("话题：\(item.contactTopic ?? item.content) · 窗口 \(item.contactWindowMinutes ?? 30) 分钟").font(.footnote); Text(["expired","claim_expired"].contains(item.contactReason ?? "") ? EchoSharedReference.copy_followup_contact_expired : item.contactLabel).font(.caption).foregroundStyle(EchoPalette.muted)}
                    if !item.supportsNativeTransitions {
                        Text("\(item.repeatRule == "daily" ? "每日跟进" : "此重复跟进")请在 Web 端管理；手机端暂不能修改。")
                            .font(.footnote).foregroundStyle(EchoPalette.muted)
                    }
                    if item.status == "pending" && item.supportsNativeTransitions {
                        HStack {
                            if item.repeatRule != "daily" || (item.due && item.paused != true) {Button(item.repeatRule == "daily" ? "完成本次" : "完成") {Task {await change(item,to:"done")}}.frame(minHeight:44)}
                            if item.repeatRule == "daily" {Button(item.paused == true ? "恢复" : "暂停") {Task {await change(item,to:item.paused == true ? "resumed" : "paused")}}.frame(minHeight:44)}
                            Button("取消跟进", role:.destructive) { cancelling = item }.frame(minHeight:44)
                        }.disabled(updatingID != nil)
                    }
                }.echoCard()
            }
            Button("刷新跟进") { Task { await refresh() } }.frame(minHeight:44).disabled(loading)
        }.padding(20) }.background(EchoBackground()).navigationTitle("应用内跟进").echoInlineNavigationTitle().echoProtectingEdits(loading || updatingID != nil || cancelling != nil || composer)
        .onChange(of:store.remoteReadRevision) {_,_ in loadVersion=UUID();records=store.followups;error=nil}
        .task {
            await store.refreshFollowups(); await refresh()
            while !Task.isCancelled {
                do {try await Task.sleep(nanoseconds:45_000_000_000)} catch {return}
                if scenePhase == .active {await store.refreshFollowups(); await refresh()}
            }
        }
        .onChange(of:scenePhase) { _, phase in if phase == .active { Task { await store.refreshFollowups(); await refresh() } } }
        .sheet(isPresented:$composer,onDismiss:{ Task { await refresh() } }) { NavigationStack { FollowupComposerView() } }
        .confirmationDialog(cancelling?.repeatRule == "daily" ? "取消整个每日跟进？" : "取消这次跟进？",isPresented:Binding(get:{ cancelling != nil },set:{ if !$0 { cancelling = nil } }),titleVisibility:.visible) {
            Button("确认取消",role:.destructive) { if let item = cancelling { Task { await change(item,to:"cancelled") } }; cancelling = nil }
            Button("保留",role:.cancel) { cancelling = nil }
        } message: {Text(cancelling?.repeatRule == "daily" ? "取消后，之后的每日跟进也不会再出现。" : "取消后不会再显示为待跟进。") }
    }
    private func label(_ item: EchoFollowup) -> String {
        if item.paused == true && item.status == "pending" { return "已暂停" }
        if item.quiet == true && item.status == "pending" { return "安静时段" }
        switch item.status { case "pending": return item.due ? "现在可以聊聊" : "已约好"; case "done": return "已完成"; case "cancelled": return "已取消"; default: return "状态待核对" }
    }
    private func displayDate(_ text: String, timeZone: String?) -> String {
        guard let date=EchoFollowup.parse(text) else {return text + " · 时间待核对"}
        if let timeZone, TimeZone(identifier:timeZone) == nil {return text + " · 时区待核对"}
        let zone=timeZone.flatMap {TimeZone(identifier:$0)} ?? .current
        let formatter=DateFormatter();formatter.dateStyle = .medium;formatter.timeStyle = .short;formatter.timeZone=zone
        return formatter.string(from:date) + " · " + (timeZone ?? zone.identifier + "（设备时区）")
    }
    private func refresh() async {
        guard let sid = store.sessionID, !loading else { return }
        let origin = store.scopeIdentity, client = store.api, version = loadVersion
        loading = true
        defer { loading = false }
        do {
            let value = try await client.followups(sessionID:sid)
            guard store.sessionID == sid, store.scopeIdentity == origin, version == loadVersion else { return }
            records = value; error = nil
        } catch { if store.sessionID == sid, store.scopeIdentity == origin, version == loadVersion { self.error = "跟进暂时读不到，已显示的记录可能不是最新状态：\(error.localizedDescription)" } }
    }
    private func change(_ item: EchoFollowup, to status: String) async {
        guard let sid = store.sessionID, updatingID == nil, item.supportsNativeTransitions else { return }
        let origin = store.scopeIdentity, client = store.api
        updatingID = item.id; loadVersion = UUID()
        defer { updatingID = nil }
        do {
            let updated = try await client.changeFollowup(item,status:status)
            guard store.sessionID == sid, store.scopeIdentity == origin else { return }
            if let index = records.firstIndex(where: { $0.id == updated.id }) { records[index] = updated }
            error = nil
            receipt=status == "done" ? (item.repeatRule == "daily" ? "已完成本次，下次时间已更新。" : "已标记完成。") : status == "paused" ? "已暂停这条跟进。" : status == "resumed" ? "已恢复这条跟进；不会补发错过的联系。" : "已取消跟进。"
            await refresh()
        } catch { if store.sessionID == sid, store.scopeIdentity == origin { receipt=nil; self.error = "状态尚未确认，请刷新记录核对，不会自动重试：\(error.localizedDescription)" } }
    }
}

struct FollowupComposerView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    @State private var form=EchoFollowupFormDraft(sessionID:"",origin:"")
    @State private var restored=false
    @State private var confirming=false
    @State private var busy=false
    @State private var attempted=false
    @State private var error: String?
    private var supportsDaily: Bool {store.capabilities?.features["in_app_recurring_followups"] == true}
    private var supportsContact: Bool {store.capabilities?.features["bounded_followup_contact"] == true}
    private var dateLabel: String {let f=DateFormatter();f.dateStyle = .medium;f.timeStyle = .short;f.timeZone=TimeZone(identifier:form.timeZone) ?? .current;return f.string(from:form.due)}
    private var contactScope: String {
        guard form.allowContact else {return "只作为待办，不同意主动联系。"}
        let topic=form.contactTopic.trimmingCharacters(in:.whitespacesAndNewlines)
        return "\(form.repeatRule == "daily" ? "每天每次" : "这次")到点后的 \(form.contactWindowMinutes) 分钟内，最多轻问一次；只限话题：\(topic.isEmpty ? form.content : topic)。当前 iOS 不自动呈现。"
    }
    var body: some View {
        Form {
            Section("约好一件事") {
                TextField("想在下次聊什么？",text:$form.content,axis:.vertical).lineLimit(2...6)
                Picker("重复",selection:$form.repeatRule) {Text("一次").tag("once"); if supportsDaily {Text("每天").tag("daily")}}
                TextField("IANA 时区，例如 Asia/Shanghai",text:$form.timeZone).echoURLInput()
                DatePicker("第一次时间",selection:$form.due,displayedComponents:[.date,.hourAndMinute]).environment(\.timeZone,TimeZone(identifier:form.timeZone) ?? .current)
                if form.repeatRule == "daily" {Text("按所选时区每天同一时间；完成本次后才排下一次，不在离线期间追赶。 ").font(.footnote)}
                Toggle("这条跟进也遵守安静时段",isOn:$form.usesQuietHours)
                if form.usesQuietHours {TextField("开始 HH:mm",text:$form.quietStart);TextField("结束 HH:mm",text:$form.quietEnd)}
            }.disabled(attempted || busy)
            if supportsContact {
                Section("是否允许轻问一次") {
                    Toggle(EchoSharedReference.copy_followup_contact_consent,isOn:$form.allowContact)
                    if form.allowContact {
                        Stepper("有效窗口 \(form.contactWindowMinutes) 分钟",value:$form.contactWindowMinutes,in:5...180,step:5)
                        TextField("联系的话题（留空使用上面的内容）",text:$form.contactTopic,axis:.vertical)
                        Text(contactScope).font(.footnote)
                        Text("改变边界、拒绝或撤回来源后，已有轻问许可失效，之后需重新约定；过期也不补发。此许可可由已实现呈现的 Web / 桌面使用；当前 iOS 只显示待办，不自动弹出轻问或发系统通知。").font(.footnote)
                    } else {Text(EchoSharedReference.copy_followup_contact_default + " 仍可查看、完成或取消待办。").font(.footnote)}
                }.disabled(attempted || busy)
            }
            Section {
                Text("不会自动发消息、推送通知或写入手机系统。保存后原请求在核对前不能更改。").font(.footnote).foregroundStyle(EchoPalette.muted)
                if let error {Text(error).font(.footnote)}
                if let notice=store.followupNotice {Text(notice).font(.footnote).foregroundStyle(EchoPalette.muted)}
                if !attempted {Button("核对并安排") {confirming=true}.disabled(busy || form.content.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || form.content.unicodeScalars.count > 1000 || form.due <= Date())}
                else {Text("原请求保存在本机。关闭后在列表只读核对，不能新建第二次发送。").font(.footnote)}
            }
        }.navigationTitle("安排下次跟进").echoProtectingEdits().echoInlineNavigationTitle()
        .toolbar {ToolbarItem(placement:.cancellationAction) {Button("关闭") {dismiss()}.disabled(busy)}}
        .interactiveDismissDisabled(busy)
        .onAppear {
            guard !restored, let sid=store.sessionID else {return}
            if let draft=store.followupDraft {form=EchoFollowupFormDraft(draft)}
            else if let draft=store.followupForm {form=draft}
            else {form=EchoFollowupFormDraft(sessionID:sid,origin:store.scopeIdentity)}
            restored=true
        }
        .onChange(of:form) {_, value in if restored && !attempted {store.saveFollowupForm(value)}}
        .confirmationDialog("确认保存这条跟进？",isPresented:$confirming,titleVisibility:.visible) {
            Button("确认安排") {Task {await save()}};Button("再想想",role:.cancel) {}
        } message: {Text("\(form.content.trimmingCharacters(in:.whitespacesAndNewlines))\n\(dateLabel) · \(form.timeZone) · \(form.repeatRule == "daily" ? "每天" : "一次")\n\(form.usesQuietHours ? "安静时段：\(form.quietStart)–\(form.quietEnd)\n" : "")\(contactScope)")}
    }
    private func save() async {
        guard !busy, !attempted, store.pendingFollowup == nil else {return}
        guard form.sessionID == store.sessionID, form.origin == store.scopeIdentity else {error="草稿仍属于原服务 / 原对话，请先核对；没有发送。";return}
        busy=true;attempted=true;defer {busy=false}
        let saved=await store.saveFollowup(content:form.content,date:form.due,repeatRule:form.repeatRule,timeZone:form.timeZone,quietStart:form.usesQuietHours ? form.quietStart : nil,quietEnd:form.usesQuietHours ? form.quietEnd : nil,allowContact:form.allowContact,contactWindowMinutes:form.contactWindowMinutes,contactTopic:form.contactTopic)
        if saved {dismiss()} else if store.pendingFollowup == nil {attempted=false}
    }
}
