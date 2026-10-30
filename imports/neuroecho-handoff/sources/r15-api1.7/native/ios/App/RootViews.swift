import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

private enum EchoTab: CaseIterable { case today, chat, memory
    var title: String { switch self { case .today:return EchoSharedReference.copy_nav_today; case .chat:return EchoSharedReference.copy_nav_chat; case .memory:return EchoSharedReference.copy_nav_memory } }
    var symbol: String { switch self { case .today: return "sparkle"; case .chat: return "bubble.left"; case .memory: return "circle.grid.2x2" } }
}
struct EchoRootView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab: EchoTab = .today
    @State private var settings = false
    @State private var search = false
    @State private var homeSection = 0
    var body: some View {
        ZStack {
            EchoBackground()
            VStack(spacing:12) {
                HStack(spacing:12) {
                    Button { search = true } label: { Image(systemName:"magnifyingglass").frame(width:44,height:44).echoGlass() }.accessibilityLabel("搜索这段对话")
                    Spacer(minLength:0)
                    HStack(spacing:8) { EchoOrb(size:30); Text(EchoSharedReference.copy_app_name).font(.body.weight(.semibold)); Text(store.pending != nil ? "正在核对" : store.draft.isEmpty ? EchoSharedReference.copy_state_quiet : "在听你说").font(.caption).foregroundStyle(EchoPalette.muted) }.padding(.horizontal,12).frame(minHeight:44).echoGlass()
                    Spacer(minLength:0)
                    Button { settings = true } label: { Image(systemName:"slider.horizontal.3").frame(width:44,height:44).echoGlass() }.accessibilityLabel("设置、连接和任务")
                }.padding(.horizontal,20)
                if store.conversation == nil {
                    Spacer()
                    VStack(alignment:.leading,spacing:16) {
                        EchoOrb();Text("回响还没连上").font(.title2.bold())
                        Text(store.error ?? store.connectionNotice ?? "正在读取同一段对话…").foregroundStyle(EchoPalette.muted)
                        if !store.isRemote {Button("重新连接") {Task {await store.connect()}}.buttonStyle(EchoPrimaryButton())}
                        else if let profile=store.deviceProfile,!store.forgottenDeviceGenerations.contains(profile.credentialGeneration) {Button("验证并恢复设备连接") {Task {await store.restoreDeviceConnection()}}.buttonStyle(EchoPrimaryButton()).disabled(store.verifyingDevice)}
                        NavigationLink("安全连接你的回响") {DeviceConnectionView()}
                        Button("设置与本机开发连接") {settings=true}.frame(minHeight:44)
                    }.echoCard().padding(20)
                    Spacer()
                } else {
                    switch tab {
                    case .today:
                        ScrollView { VStack(spacing:16) {
                            VStack(alignment:.leading,spacing:12) { Text("给今天，留一点空白。").font(.largeTitle.bold()); Picker("查看",selection:$homeSection) { Text("今天").tag(0); Text("记忆").tag(1); Text("连接").tag(2) }.pickerStyle(.segmented) }.padding(.horizontal,4)
                            if homeSection == 0 { TodayCards(onChat:{ text in store.carryToChat(text); tab = .chat },onMemory:{tab = .memory}) }
                            if homeSection == 1 { MemoryListView() }
                            if homeSection == 2 { ConnectionsView() }
                        }.padding(20) }.refreshable {await store.checkUpdatesExplicitly()}
                    case .chat: ChatStreamView()
                    case .memory: ScrollView { VStack(alignment:.leading,spacing:16) { Text("慢慢认识你").font(.largeTitle.bold()); MemoryListView() }.padding(20) }
                    }
                }
            }.padding(.top,8)
        }.foregroundStyle(EchoPalette.ink).tint(EchoPalette.ink)
        .safeAreaInset(edge:.bottom,spacing:10) {
            VStack(spacing:10) {
                ChangeRefreshNotice()
                if tab == .chat, store.conversation != nil { ChatComposer() }
                HStack(spacing:8) { ForEach(EchoTab.allCases,id:\.self) { item in
                    Button { tab = item } label: { VStack(spacing:4) { Image(systemName:item.symbol).font(.title3); Text(item.title).font(.caption) }.frame(maxWidth:.infinity,minHeight:52).background(tab == item ? .white.opacity(0.92) : .clear,in:Capsule()) }.accessibilityAddTraits(tab == item ? .isSelected : [])
                } }.padding(6).echoGlass()
            }.padding(.horizontal,20).padding(.bottom,6)
        }
        .sheet(isPresented:$settings) { NavigationStack { SettingsView() } }
        .sheet(isPresented:$search) { NavigationStack { SearchView(onMessage:{ id in store.focusMessage(id); search = false; tab = .chat }) } }
        .task {await store.connect();store.setChangeMonitoringActive(scenePhase == .active)}
        .task(id:"\(store.scopeIdentity)|\(store.sessionID ?? "")|\(store.canDiscoverChanges)|\(scenePhase == .active)") {store.setChangeMonitoringActive(scenePhase == .active)}
    }
}
struct TodayCards: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.scenePhase) private var scenePhase
    let onChat: (String) -> Void
    let onMemory: () -> Void
    @State private var tasks = false
    @State private var connections = false
    @State private var showMood = false
    @State private var showFollowups = false
    @State private var dueFollowups: [EchoFollowup] = []
    @State private var followupRefreshError = false
    @State private var followupScope = ""
    @State private var followupRequest = UUID()
    var body: some View {
        let bookmark = store.conversation?.bookmark
        VStack(spacing:16) {
            if followupRefreshError {
                Text("跟进暂时无法刷新，显示的是上次读取的结果。请检查连接后再试。")
                    .font(.footnote).foregroundStyle(EchoPalette.muted).echoCard()
            }
            if !dueFollowups.isEmpty {
                VStack(alignment:.leading,spacing:10) {
                    Text("待你查看的跟进").font(.headline)
                    Text(dueFollowups[0].content).textSelection(.enabled)
                    Text("这是被动待办列表，没有主动轻问或发送通知。").font(.footnote).foregroundStyle(EchoPalette.muted)
                    Button("查看跟进") { showFollowups = true }.frame(minHeight:44)
                }.echoCard()
            }
            VStack(alignment:.leading,spacing:14) {
                EchoOrb(size:250).frame(maxWidth:.infinity).padding(.vertical,8)
                Text(bookmark == nil ? "从此刻想说的开始" : "你上次停在这里").font(.title2.bold())
                Text(bookmark?.note ?? store.nextStep?.step ?? "也可以先不安排什么，聊一件正在发生的小事。")
                if let next = bookmark?.nextStep, !next.isEmpty { Text(next).foregroundStyle(EchoPalette.muted) }
                Button("带回对话，继续说") { onChat(bookmark?.nextStep.flatMap { $0.isEmpty ? nil : $0 } ?? bookmark?.note ?? store.nextStep?.step ?? "我想聊聊今天") }.buttonStyle(EchoPrimaryButton())
                Text(EchoSharedReference.copy_chat_draft_disclosure).font(.footnote).foregroundStyle(EchoPalette.muted)
            }.echoCard()
            VStack(alignment:.leading,spacing:12) { Text("先核对，再记下").font(.headline); Text("\(store.conversation?.memories.filter { $0.status != "deleted" }.count ?? 0) 条理解，随时可以纠正或忘掉。").foregroundStyle(EchoPalette.muted); Button("打开记忆",action:onMemory).frame(minHeight:44) }.echoCard()
            VStack(alignment:.leading,spacing:12) {Text(EchoSharedReference.copy_mood_title).font(.headline);Text(EchoSharedReference.copy_mood_context).foregroundStyle(EchoPalette.muted);Button(EchoSharedReference.copy_mood_open) {showMood=true}.frame(minHeight:44).disabled(store.capabilities?.features["daily_mood_entries"] != true);if store.capabilities == nil {Text("服务能力还未核对，可在设置中检查更新；先聊天也可以。").font(.footnote)} else if store.capabilities?.features["daily_mood_entries"] != true {Text("当前服务还未提供心情记录，先聊天也可以。").font(.footnote)}}.echoCard()
            if !store.isRemote {
            VStack(alignment:.leading,spacing:12) { Text("你决定下一步").font(.headline); Text("\(store.actions.count) 个保存的动作或草稿。不会自动发送，也不会自动写入手机系统。").foregroundStyle(EchoPalette.muted); Button("查看任务与草稿") { tasks = true }.frame(minHeight:44) }.echoCard()
            }
            VStack(alignment:.leading,spacing:12) { Text("它能看的，由你选择").font(.headline); Text(store.sources.isEmpty ? "还没有接入资料。先聊聊也可以。" : store.sources.map(\.displayTitle).joined(separator:"、")).foregroundStyle(EchoPalette.muted); Button("管理 \(store.sources.count) 份已接资料") { connections = true }.frame(minHeight:44) }.echoCard()
        }.sheet(isPresented:$tasks,onDismiss:{ Task { await refreshDueFollowups() } }) { NavigationStack { ActionsView() } }.sheet(isPresented:$connections) { NavigationStack { ConnectionsView() } }
        .sheet(isPresented:$showFollowups,onDismiss:{ Task { await refreshDueFollowups() } }) { NavigationStack { FollowupsView().toolbar { ToolbarItem(placement:.cancellationAction) { Button("关闭") { showFollowups = false } } } } }
        .sheet(isPresented:$showMood) {NavigationStack {MoodView(onChat:onChat)}}
        .onChange(of:store.remoteReadRevision) {_,_ in followupRequest=UUID();dueFollowups=store.followups.filter { $0.isReviewAvailable };followupRefreshError=false}
        .task(id:"\(store.sessionID ?? "")|\(store.scopeIdentity)|\(scenePhase == .active)") {
            guard scenePhase == .active, store.sessionID != nil else { return }
            while !Task.isCancelled {
                await refreshDueFollowups()
                try? await Task.sleep(for:.seconds(45))
            }
        }
    }
    private func refreshDueFollowups() async {
        guard let sid = store.sessionID else { dueFollowups = []; followupRefreshError = false; return }
        let client = store.api, origin = store.scopeIdentity
        let scope = "\(origin)|\(sid)", request = UUID()
        if followupScope != scope { dueFollowups = []; followupRefreshError = false; followupScope = scope }
        followupRequest = request
        do {
            let result = try await client.followups(sessionID:sid)
            guard !Task.isCancelled, store.sessionID == sid, store.scopeIdentity == origin, followupRequest == request else { return }
            dueFollowups = result.filter { $0.isReviewAvailable }
            followupRefreshError = false
        } catch {
            if !Task.isCancelled, store.sessionID == sid, store.scopeIdentity == origin, followupRequest == request { followupRefreshError = true }
        }
    }
}
struct ChatStreamView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var endingLocalWait = false
    @State private var remember: EchoMessage?
    @State private var tagging: EchoMessage?
    @State private var memoryDraft: MessageMemoryDraft?
    @StateObject private var speech=SpeechController()
    private var readableReplies: [EchoSpeechTarget] {
        store.visibleMessages.compactMap {EchoSpeechTarget.visibleReply($0,origin:store.scopeIdentity,sessionID:store.sessionID,foreground:scenePhase == .active)}
    }
    private func reconcileSpeech() {speech.reconcile(messages:store.visibleMessages,origin:store.scopeIdentity,sessionID:store.sessionID,foreground:scenePhase == .active)}
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView { LazyVStack(spacing:16) {
                ScrollView(.horizontal,showsIndicators:false) { HStack(spacing:8) { ForEach(store.topicLabels,id:\.self) { label in Button { store.selectedTopic = label } label: { Text(label).font(.subheadline).padding(.horizontal,14).frame(minHeight:44).background(store.selectedTopic == label ? .white.opacity(0.94) : EchoPalette.ink.opacity(0.07),in:Capsule()) }.accessibilityAddTraits(store.selectedTopic == label ? .isSelected : []) } } }
                Text("话题只筛选本设备的视图，不建立新对话，也不成为记忆。").font(.footnote).foregroundStyle(EchoPalette.muted)
                Text(EchoSharedReference.copy_voice_disclosure).font(.footnote).foregroundStyle(EchoPalette.muted)
                if store.visibleMessages.isEmpty { Text(store.selectedTopic == "全部" ? "先说此刻想说的，资料可以稍后再连。" : "这个话题还没有消息。长按已有消息可以标记。").foregroundStyle(EchoPalette.muted).echoCard() }
                ForEach(store.visibleMessages) { message in
                    HStack { if message.role == "user" { Spacer(minLength:40) }; VStack(alignment:.leading,spacing:8) {
                        ForEach(Array(message.displayParts.enumerated()),id:\.offset) { _, part in Text(part).font(.body).lineSpacing(5).textSelection(.enabled).padding(16).frame(maxWidth:310,alignment:.leading).background(message.role == "user" ? Color(red:190/255,green:205/255,blue:1).opacity(0.55) : .white.opacity(0.94),in:RoundedRectangle(cornerRadius:22)) }
                        if EchoSpeechTarget.visibleReply(message,origin:store.scopeIdentity,sessionID:store.sessionID,foreground:scenePhase == .active) != nil {
                            HStack(spacing:8) {
                                let active=speech.active?.target.messageID == message.id
                                Button {speech.toggle(message,origin:store.scopeIdentity,sessionID:store.sessionID,foreground:scenePhase == .active)} label: {
                                    Label(active ? EchoSharedReference.copy_voice_stop : EchoSharedReference.copy_voice_read,systemImage:active ? "stop.fill" : "speaker.wave.2")
                                }.font(.footnote).frame(minWidth:44,minHeight:44).accessibilityLabel(active ? EchoSharedReference.copy_voice_stop : EchoSharedReference.copy_voice_read)
                                if active,speech.active?.phase == .preparing {Text(EchoSharedReference.copy_voice_preparing).font(.footnote).foregroundStyle(EchoPalette.muted)}
                                else if speech.unavailableMessageID == message.id {Text(EchoSharedReference.copy_voice_unavailable).font(.footnote).foregroundStyle(EchoPalette.muted)}
                            }.frame(maxWidth:310,alignment:.leading)
                        }
                    }.contextMenu {
                        Button("复制全文") { copyEchoText(message.text) }
                        Button("标记话题") { tagging = message }
                        if message.role == "user" { Button("记下这句") { remember = message }.disabled(store.busy || store.pending != nil) }
                        if message.role == "user" { Button("整理为一条记忆") { memoryDraft = MessageMemoryDraft(text:message.text) }.disabled(store.busy || store.pending != nil) }
                    }; if message.role != "user" { Spacer(minLength:40) } }.id(message.id)
                }
                if store.pending == nil, let message=store.conversation?.messages.last(where:{$0.role == "assistant"}), message.deliveryPending == true {
                    VStack(alignment:.leading,spacing:8) {
                        Text("这条回复还有后续内容，正在依次展开。").font(.footnote).foregroundStyle(EchoPalette.muted)
                        Button("先停在这里") { Task { await store.stopDelivery(messageID:message.id) } }.frame(minHeight:44).disabled(store.busy || store.capabilities?.features["chat_delivery_targeted_stop"] != true)
                        if store.capabilities?.features["chat_delivery_targeted_stop"] != true {Text("当前服务尚未声明按消息停止能力，更新服务后可用。").font(.footnote).foregroundStyle(EchoPalette.muted)}
                    }.echoCard()
                }
                if let turn = store.pending { VStack(alignment:.leading,spacing:12) { Text(turn.cancelWanted ? "已请求停止，正在等待确认。" : "这次发送尚待确认").font(.headline); Text(turn.text).lineLimit(4); Text("待确认文字暂存在这台设备，核对成功后清除。").font(.footnote).foregroundStyle(EchoPalette.muted); HStack { Button("核对状态") { Task { await store.recoverPending() } }.disabled(store.busy); Button("停止这次回复") { Task { await store.cancelPending() } } }; if store.retryAllowed { Button("使用原标识重试这次发送") { Task { await store.retryPending() } }.disabled(store.busy); Text("尚未找到服务端记录。手动重试仍使用原文字与原发送标识；不会另建一次发送。").font(.footnote).foregroundStyle(EchoPalette.muted) } }.echoCard() }
                if store.pending != nil, store.canEndLocalWait { Button("核对后，结束本机等待") { endingLocalWait = true }.frame(minHeight:44).disabled(store.busy) }
                if let error = store.error { Text(error).font(.footnote).foregroundStyle(EchoPalette.muted).echoCard() }
            }.padding(20) }.onChange(of:store.conversation?.messages.last?.id) { _, id in if let id, store.pending != nil, store.selectedTopic == "全部" { proxy.scrollTo(id,anchor:.bottom) } }.onChange(of:store.jumpRequestID) { _, _ in if let id = store.jumpToMessageID { proxy.scrollTo(id,anchor:.center) } }.onAppear { if let id = store.jumpToMessageID ?? store.visibleMessages.last?.id { proxy.scrollTo(id,anchor:.bottom) } }
        }.echoProtectingEdits(endingLocalWait || remember != nil || tagging != nil || memoryDraft != nil).onChange(of:readableReplies) {_,_ in reconcileSpeech()}
        .onChange(of:scenePhase) {_,_ in reconcileSpeech()}
        .onChange(of:store.remoteReadRevision) {_,_ in _ = speech.stop()}
        .onDisappear {_ = speech.stop()}
        .task(id:"\(store.scopeIdentity)|\(store.sessionID ?? "")|\(scenePhase == .active)|\(store.conversation?.messages.contains(where: { $0.deliveryPending == true }) == true)") {
            while !Task.isCancelled, scenePhase == .active, let message = store.conversation?.messages.first(where: { $0.deliveryPending == true }) {
                let delay = max(100, min(2000, message.deliveryNextMs ?? 800))
                try? await Task.sleep(for:.milliseconds(delay))
                guard !Task.isCancelled else { break }
                await store.refreshDelivery()
            }
        }.confirmationDialog("结束本机等待？",isPresented:$endingLocalWait,titleVisibility:.visible) {
            Button("我已核对，结束本机等待") { Task { await store.endLocalWaitAfterReview() } }
            Button("继续等待",role:.cancel) {}
        } message: { Text("原请求的结果仍未确认，结束等待不代表服务器已取消。会重新读取聊天记录，再把原话放回输入框；不会重新发送。请先确认是否已有这句话，再决定后续操作。") }
        .confirmationDialog("记下这句原话？",isPresented:Binding(get:{remember != nil},set:{if !$0 {remember = nil}}),titleVisibility:.visible) {
            Button("确认记下，相关时可参考") { guard let message = remember else {return}; remember = nil; Task { await store.rememberQuote(message); if store.quoteNeedsManualReview {memoryDraft = MessageMemoryDraft(text:message.text,notice:"这句尚未直接选存。你可以整理下面的文字，再保存为待确认记忆；不会自动记下。") } } }
            Button("不用",role:.cancel) { remember = nil }
        } message: { Text((remember?.text ?? "") + "\n会保存在回响服务的记忆中，之后可纠正或忘掉。不记也可以。") }
        .sheet(item:$tagging) { message in NavigationStack { TopicEditorView(message:message) } }
        .sheet(item:$memoryDraft) { draft in NavigationStack { NewMemoryView(initialText:draft.text,notice:draft.notice) } }
    }
}
private struct MessageMemoryDraft: Identifiable { let id = UUID(); let text: String; var notice: String = "下方将作为你手动整理的记忆，仍需核对后确认。" }

private func copyEchoText(_ text: String) {
    #if canImport(UIKit)
    UIPasteboard.general.string = text
    #elseif canImport(AppKit)
    NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType:.string)
    #endif
}
struct ChatComposer: View {
    @EnvironmentObject private var store: EchoStore
    var body: some View {
        HStack(alignment:.bottom,spacing:8) {
            TextField("说点什么…",text:$store.draft,axis:.vertical).lineLimit(1...5).font(.body).padding(.vertical,12).padding(.leading,16)
            Button { Task { await store.send() } } label: { Image(systemName:"arrow.up").font(.headline).foregroundStyle(.white).frame(width:44,height:44).background(EchoPalette.ink,in:Circle()) }.accessibilityLabel("发送这段话").disabled(store.pending != nil || store.busy || store.draft.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty).padding(6)
        }.echoGlass()
    }
}
struct SearchView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    let onMessage: (String) -> Void
    var body: some View {
        let hits = EchoWorkspace.search(store.conversation,query:query)
        List {
            Text("只搜索当前已加载的对话与记忆，不上传搜索词。").font(.footnote).foregroundStyle(EchoPalette.muted)
            if !query.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty, hits.isEmpty { Text("没有匹配的记录。") }
            ForEach(hits) { hit in
                if hit.kind == .memory, let memory = store.conversation?.memories.first(where:{$0.id == hit.recordID}) {
                    NavigationLink { MemoryDetailView(memory:memory) } label: { SearchHitLabel(hit:hit) }
                } else { Button { onMessage(hit.recordID) } label: { SearchHitLabel(hit:hit) }.buttonStyle(.plain) }
            }
        }.searchable(text:$query,prompt:"搜索这段对话和记忆").navigationTitle("找一句说过的话").toolbar { ToolbarItem(placement:.cancellationAction) { Button("关闭") { dismiss() } } }
    }
}
private struct SearchHitLabel: View {
    let hit: EchoSearchHit
    var body: some View { VStack(alignment:.leading,spacing:8) { Text(hit.label).font(.caption).foregroundStyle(EchoPalette.muted); Text(hit.text).font(.body).foregroundStyle(EchoPalette.ink) }.padding(.vertical,8) }
}
private struct TopicEditorView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    let message: EchoMessage
    @State private var label = ""
    var body: some View {
        Form {
            Section("标记话题") { Text(message.text).lineLimit(5); TextField("最多20字",text:$label); Text("仅本设备的视图分类，不是个人记忆，也不会建立新对话。").font(.footnote) }
            Button("保存标记") { store.setTopic(label,for:message.id); dismiss() }.disabled(EchoWorkspace.normalizedTopic(label) == nil)
        }.navigationTitle("标记话题").echoProtectingEdits().toolbar { ToolbarItem(placement:.cancellationAction) { Button("不用") { dismiss() } } }.onAppear { label = EchoWorkspace.topic(for:message.id,assignments:store.topics) }
    }
}
