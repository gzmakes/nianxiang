import SwiftUI

/// Independent diary state. It never sends chat, creates memory, or claims contact.
@MainActor final class MoodStore: ObservableObject {
    @Published private(set) var draft: EchoMoodDraft?
    @Published private(set) var records: [EchoMood] = []
    @Published private(set) var ready=false
    @Published private(set) var busy=false
    @Published private(set) var supported=false
    @Published private(set) var ledgerSupported=false
    @Published private(set) var notice=""
    private var client: EchoAPI?
    private var sid=""
    private var origin=""
    private var generation=UUID()
    private var sequence=0
    private var storageReady=true
    private let defaults: UserDefaults
    private let writer: ((String,Data) -> Bool)?
    init(defaults: UserDefaults = .standard, writer: ((String,Data) -> Bool)? = nil) {self.defaults=defaults;self.writer=writer}
    var current: EchoMood? {records.first {$0.date == draft?.day}}
    var canSave: Bool {supported && ready && !busy && storageReady && draft?.canSave == true}
    var canDelete: Bool {supported && ready && !busy && storageReady && draft?.pending == nil && draft?.dirty == false && draft?.needsReview == false && current != nil}
    var canAdoptLatest: Bool {supported && ready && !busy && draft?.needsReview == true && draft?.pending == nil}
    var canRecoverLedger: Bool {supported && ledgerSupported && !busy && storageReady && draft?.pending?.validLedgerIdentity == true}
    var canRetryLedger: Bool {canRecoverLedger && draft?.cancelRequested != true}
    func isBound(origin: String, sessionID: String?) -> Bool {self.origin == origin && sid == sessionID && draft?.origin == origin && draft?.sessionID == sessionID}
    func reviewedChatDraft(origin: String, sessionID: String?) -> String? {
        guard isBound(origin:origin,sessionID:sessionID), supported, ready, !busy, draft?.dirty == false, draft?.pending == nil, draft?.needsReview == false else {return nil}
        return current?.chatDraft
    }
    private var scopeKey: String {Data((origin+"|"+sid).utf8).base64EncodedString()}
    private var selectionKey: String {"echo.native.mood-selection.v1."+scopeKey}
    private func key(_ day: String) -> String {"echo.native.mood-draft.v1."+scopeKey+"."+day}
    @discardableResult private func persist(_ value: EchoMoodDraft) -> Bool {
        draft=value
        guard let data=try? JSONEncoder().encode(value) else {storageReady=false;return false}
        if let writer {storageReady=writer(key(value.day),data)}
        else {defaults.set(data,forKey:key(value.day));storageReady=defaults.data(forKey:key(value.day)) == data}
        if !storageReady {notice="本机未能保存草稿；没有发送新请求。请先复制文字。"}
        return storageReady
    }
    private func load(_ day: String) {
        let cached=defaults.data(forKey:key(day)).flatMap {try? JSONDecoder().decode(EchoMoodDraft.self,from:$0)}
        let value=cached.flatMap {$0.origin == origin && $0.sessionID == sid && $0.day == day ? $0 : nil}
            ?? EchoMoodDraft(origin:origin,sessionID:sid,day:day,record:records.first {$0.date == day})
        persist(value)
    }
    func bind(api: EchoAPI, sessionID: String, supported: Bool, ledgerSupported: Bool = false) async {
        generation=UUID();sequence=0;busy=false;ready=false;records=[];notice=""
        client=api;origin=api.storageNamespace;sid=sessionID;self.supported=supported;self.ledgerSupported=ledgerSupported
        let saved=defaults.string(forKey:selectionKey)
        load(saved.flatMap {EchoMood.validDay($0) ? $0 : nil} ?? EchoMood.day())
        guard supported else {notice="当前服务未声明每日心情能力；没有读取或上传日记。";return}
        await refresh()
    }
    func suspend() {generation=UUID();sequence += 1;busy=false;ready=false}
    func select(day: String) async {
        guard !busy, supported, EchoMood.validDay(day) else {return}
        generation=UUID();ready=false;defaults.set(day,forKey:selectionKey);load(day);await refresh()
    }
    func edit(x: Double? = nil, y: Double? = nil, note: String? = nil) {
        guard var value=draft, !busy, value.pending == nil else {return}
        if let x {value.x=x;value.xSelected=true}
        if let y {value.y=y;value.ySelected=true}
        if let note {value.note=note}
        value.dirty=true;persist(value)
    }
    func discardDraft() {
        guard !busy, let draft, draft.pending == nil, ready else {return}
        persist(EchoMoodDraft(origin:origin,sessionID:sid,day:draft.day,record:current));notice="已放弃未保存修改；记录未变。"
    }
    func adoptLatestVersion() {
        guard canAdoptLatest, var value=draft else {return}
        value.expectedUpdatedAt=current?.updatedAt;value.needsReview=false;value.dirty=true
        persist(value);notice="只采用了刚核对的版本。你的草稿仍在；再次确认才会保存。"
    }
    func refresh() async {
        guard supported, let client, !busy else {return}
        if let pending=draft?.pending,pending.hasLedgerIdentity {
            guard ledgerSupported else {ready=false;notice="当前服务未声明提交账本能力，原请求仍保留；没有改用旧接口重发。";return}
            guard pending.validLedgerIdentity else {ready=false;notice="原请求身份不完整，草稿仍保留。请人工核对；不会补造编号或发送。";return}
            await runLedger(.check,mutation:pending);return
        }
        let epoch=generation, expectedSID=sid, expectedOrigin=origin
        sequence += 1;let ticket=sequence;busy=true
        defer {if epoch == generation && ticket == sequence {busy=false}}
        do {
            let value=try await client.moods(sessionID:expectedSID)
            guard epoch == generation, ticket == sequence, sid == expectedSID, origin == expectedOrigin, !Task.isCancelled else {return}
            records=value;ready=true;reconcile()
        } catch {
            guard epoch == generation, ticket == sequence, sid == expectedSID, origin == expectedOrigin, !Task.isCancelled else {return}
            ready=false;notice="暂时读不到记录，草稿与未决状态仍保留；没有重新保存或删除。"
        }
    }
    private func reconcile() {
        guard var value=draft else {return}
        if let pending=value.pending {
            if pending.kind == .save, let current, pending.matches(current) {
                persist(EchoMoodDraft(origin:origin,sessionID:sid,day:value.day,record:current));notice="已只读核对到相同的保存内容。";return
            }
            if pending.kind == .delete, current == nil {
                persist(EchoMoodDraft(origin:origin,sessionID:sid,day:value.day));notice="已核对：这一天当前没有记录；这不是补造删除回执。";return
            }
            // An existing version that is now absent cannot be written by the
            // old CAS. This differs from an unknown create with expected null.
            if (current != nil && current?.updatedAt != pending.expectedUpdatedAt) || (current == nil && pending.expectedUpdatedAt != nil) {
                value.pending=nil;value.needsReview=true;value.dirty=true;persist(value)
                notice="最新记录与原请求不同。原草稿保留；看过最新内容后，明确采用新版本再决定。";return
            }
            notice="原请求仍未确认。没有记录或仍是旧版本，都不能证明请求未执行；只读核对，不会重发。";return
        }
        if value.dirty || value.needsReview {
            if value.expectedUpdatedAt != current?.updatedAt {value.needsReview=true;persist(value);notice="这一天的记录已变化；草稿保留，请先核对最新内容。"}
        } else {persist(EchoMoodDraft(origin:origin,sessionID:sid,day:value.day,record:current));notice=""}
    }
    func save() async {
        guard canSave, let draft else {return}
        await startMutation(EchoMoodMutation(kind:.save,draft:draft))
    }
    func delete() async {
        guard canDelete, let draft else {return}
        await startMutation(EchoMoodMutation(kind:.delete,draft:draft))
    }
    private func startMutation(_ newMutation: EchoMoodMutation) async {
        guard ledgerSupported else {await mutateLegacy(newMutation);return}
        guard var value=draft else {return}
        do {
            let mutation=try newMutation.preparedForLedger(),old=value
            value.pending=mutation;value.operationState=nil;value.cancelRequested=false
            guard persist(value) else {draft=old;return}
            await runLedger(.apply,mutation:mutation)
        } catch {notice=error.localizedDescription}
    }
    /// A retry is a separate explicit user action. This never prepares a new ID.
    func retryOperation() async {
        guard canRetryLedger,let mutation=draft?.pending else {return}
        await runLedger(.apply,mutation:mutation)
    }
    func cancelOperation() async {
        guard canRecoverLedger,var value=draft,let mutation=value.pending else {return}
        value.cancelRequested=true
        guard persist(value) else {return}
        await runLedger(.cancel,mutation:mutation)
    }
    private enum LedgerAction {case check,apply,cancel}
    private func runLedger(_ action: LedgerAction,mutation: EchoMoodMutation) async {
        guard ledgerSupported,supported,!busy,storageReady,mutation.validLedgerIdentity,let client,draft?.pending?.localID == mutation.localID else {return}
        guard action != .apply || draft?.cancelRequested != true else {return}
        let epoch=generation,expectedSID=sid,expectedOrigin=origin
        sequence += 1;let ticket=sequence;busy=true
        defer {if epoch == generation && ticket == sequence {busy=false}}
        do {
            let receipt: EchoMoodOperation
            switch action {
            case .check:receipt=try await client.moodOperation(sessionID:expectedSID,mutation:mutation)
            case .apply:receipt=try await client.applyMoodOperation(sessionID:expectedSID,mutation:mutation)
            case .cancel:receipt=try await client.cancelMoodOperation(sessionID:expectedSID,mutation:mutation)
            }
            guard valid(epoch,ticket,expectedSID,expectedOrigin,mutation),var value=draft else {return}
            value.operationState=receipt.state
            guard persist(value) else {ready=false;return}
            // A ledger result describes the original operation, not today's row.
            // Even a known terminal response needs a separate fresh diary GET.
            let latest=try await client.moods(sessionID:expectedSID)
            guard valid(epoch,ticket,expectedSID,expectedOrigin,mutation) else {return}
            records=latest;ready=true;reconcileLedger(receipt,mutation:mutation)
        } catch {
            guard valid(epoch,ticket,expectedSID,expectedOrigin,mutation) else {return}
            ready=false
            notice=draft?.cancelRequested == true ? "取消结果仍待核对。取消意图已保留；只能核对或再次请求同一次取消，不会再提交原写入。" : "这次提交仍待核对。原编号与原内容已保留；可以只读核对，或明确选择用原请求重试、取消。"
        }
    }
    private func reconcileLedger(_ receipt: EchoMoodOperation,mutation: EchoMoodMutation) {
        guard var value=draft else {return}
        guard receipt.state != "not_found" else {
            notice=value.cancelRequested == true ? "账本暂未找到这次提交。取消意图仍保留；可再次取消，不能重新提交。" : "账本暂未找到这次提交，不代表原请求不会晚到。草稿保持锁定；由你选择核对、原请求重试或取消。"
            return
        }
        if receipt.state == "applied" {
            if mutation.kind == .save,let current,mutation.matches(current),current.updatedAt == receipt.resultUpdatedAt {
                persist(EchoMoodDraft(origin:origin,sessionID:sid,day:value.day,record:current))
                notice=EchoSharedReference.copy_mood_recovery_applied;return
            }
            if mutation.kind == .delete,current == nil {
                persist(EchoMoodDraft(origin:origin,sessionID:sid,day:value.day))
                notice=EchoSharedReference.copy_mood_recovery_applied+" 这一天当前没有记录。";return
            }
            value.pending=nil;value.operationState=nil;value.cancelRequested=nil;value.needsReview=true;value.dirty=true
            persist(value);notice=EchoSharedReference.copy_mood_recovery_applied+" 当前记录已有变化；原草稿保留，请先核对最新版本。";return
        }
        value.pending=nil;value.operationState=nil;value.cancelRequested=nil;value.dirty=true
        value.needsReview=receipt.state == "conflict" || value.expectedUpdatedAt != current?.updatedAt
        persist(value)
        notice=receipt.state == "cancelled" ? EchoSharedReference.copy_mood_recovery_cancelled : "原提交因版本冲突没有写入。草稿保留，请核对并明确采用最新版本；不会自动重试。"
    }
    private func mutateLegacy(_ mutation: EchoMoodMutation) async {
        guard let client, var value=draft else {return}
        let old=value, epoch=generation, expectedSID=sid, expectedOrigin=origin
        value.pending=mutation
        guard persist(value) else {draft=old;return}
        busy=true;sequence += 1;let ticket=sequence
        defer {if epoch == generation && sequence == ticket {busy=false}}
        do {
            if mutation.kind == .save {
                let saved=try await client.saveMood(sessionID:expectedSID,mutation:mutation)
                guard valid(epoch,ticket,expectedSID,expectedOrigin,mutation) else {return}
                records.removeAll {$0.date == mutation.day};records.append(saved)
                persist(EchoMoodDraft(origin:origin,sessionID:sid,day:mutation.day,record:saved));notice="已记下。这份日记默认不加入模型或长期记忆。"
            } else {
                try await client.deleteMood(sessionID:expectedSID,mutation:mutation)
                guard valid(epoch,ticket,expectedSID,expectedOrigin,mutation) else {return}
                records.removeAll {$0.date == mutation.day};persist(EchoMoodDraft(origin:origin,sessionID:sid,day:mutation.day));notice="已收到明确删除回执。"
            }
        } catch {
            guard valid(epoch,ticket,expectedSID,expectedOrigin,mutation), var retained=self.draft else {return}
            let status=(error as? EchoAPIError)?.statusCode
            if status == 409 {
                retained.pending=nil;retained.needsReview=true;retained.dirty=true;persist(retained);ready=false
                notice="版本有变化；草稿保留。请只读刷新并查看最新记录，明确采用版本后再确认。"
            } else if status == 400 || status == 422 {
                retained.pending=nil;retained.dirty=true;persist(retained)
                notice="服务明确拒绝了本次输入，草稿保留，可以修改后重新确认。"
            } else {notice="结果尚未确认。原内容与版本已保留，先只读核对；不会自动重发。"}
        }
    }
    private func valid(_ epoch: UUID,_ ticket: Int,_ expectedSID: String,_ expectedOrigin: String,_ mutation: EchoMoodMutation) -> Bool {
        epoch == generation && ticket == sequence && sid == expectedSID && origin == expectedOrigin && draft?.pending?.localID == mutation.localID && !Task.isCancelled
    }
}
