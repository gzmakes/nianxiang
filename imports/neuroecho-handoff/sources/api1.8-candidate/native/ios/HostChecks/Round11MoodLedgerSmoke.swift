import Foundation
import SwiftUI

@main struct Round11MoodLedgerSmoke {
    static func mutation(_ api: EchoAPI,_ sid: String,_ day: String,_ note: String,record: EchoMood? = nil,kind: EchoMoodMutation.Kind = .save) throws -> EchoMoodMutation {
        var draft=EchoMoodDraft(origin:api.baseURL.absoluteString,sessionID:sid,day:day,record:record)
        draft.x=0.3;draft.y = -0.2;draft.xSelected=true;draft.ySelected=true;draft.note=note;draft.dirty=true
        return try EchoMoodMutation(kind:kind,draft:draft).preparedForLedger()
    }
    @MainActor static func main() async {
        guard CommandLine.arguments.count == 3,CommandLine.arguments[1] == "--fresh-synthetic-service",let url=URL(string:CommandLine.arguments[2]),url.host == "127.0.0.1",let port=url.port,![18787,18789,18791].contains(port) else {print("NOT_RUN: use disposable runner only");exit(2)}
        let suite="echo.synthetic.r11-live."+UUID().uuidString,defaults=UserDefaults(suiteName:suite)!
        defer {defaults.removePersistentDomain(forName:suite)}
        var count=0
        func pass(_ s: String) {count += 1;print("PASS:",s)}
        do {
            let api=try EchoAPI(baseURL:url.absoluteString),caps=try await api.capabilities()
            precondition(caps.contractVersion == "1.5.0" && caps.features["mood_operation_ledger"] == true && caps.features["daily_mood_entries"] == true && caps.features["companion_boundaries"] == true)
            let before=try await api.conversation(),sid=before.session.id,boundary=try await api.boundary(sessionID:sid),followups=try await api.followups(sessionID:sid)
            print("HOST_R11: actual macOS URLSession + MoodStore, fresh synthetic DB, no iOS SDK/app/device.")
            let first=try mutation(api,sid,"2026-10-01","iOS-R11 raw JSON 🫶 \\ preserved"),notFound=try await api.moodOperation(sessionID:sid,mutation:first)
            precondition(notFound.state == "not_found" && notFound.operationSha256 == nil)
            let created=try await api.applyMoodOperation(sessionID:sid,mutation:first),repeated=try await api.applyMoodOperation(sessionID:sid,mutation:first),read=try await api.moodOperation(sessionID:sid,mutation:first)
            precondition(created.state == "applied" && created == repeated && repeated == read)
            let rows=try await api.moods(sessionID:sid);let row=rows.first {$0.date == first.day}!
            precondition(first.matches(row) && row.updatedAt == created.resultUpdatedAt && rows.count == 1)
            pass("real not_found metadata, exact original-ID/raw retry returns identical terminal receipt and one diary version")
            var object=try JSONSerialization.jsonObject(with:JSONEncoder().encode(first)) as! [String:Any];object["operationJSON"]=first.operationJSON!+"\n"
            let changedRaw=try JSONDecoder().decode(EchoMoodMutation.self,from:JSONSerialization.data(withJSONObject:object));precondition(changedRaw.validLedgerIdentity && changedRaw.operationHash != first.operationHash)
            do {_=try await api.applyMoodOperation(sessionID:sid,mutation:changedRaw);fatalError("identity change must conflict")} catch let e as EchoAPIError {precondition(e.statusCode == 409)}
            do {_=try await api.cancelMoodOperation(sessionID:sid,mutation:changedRaw);fatalError("cancel hash change must conflict")} catch let e as EchoAPIError {precondition(e.statusCode == 409)}
            let appliedCancel=try await api.cancelMoodOperation(sessionID:sid,mutation:first);precondition(appliedCancel == created)
            let afterIdentity=try await api.moods(sessionID:sid);precondition(afterIdentity.first {$0.date == first.day} == row)
            pass("whitespace-only identity change and wrong cancel hash get409; cancel of applied returns original result without rollback")
            let cancelled=try mutation(api,sid,"2026-10-02","iOS-R11 cancel tombstone")
            let tombstone=try await api.cancelMoodOperation(sessionID:sid,mutation:cancelled),late=try await api.applyMoodOperation(sessionID:sid,mutation:cancelled),tombstoneRead=try await api.moodOperation(sessionID:sid,mutation:cancelled)
            let afterLate=try await api.moods(sessionID:sid)
            precondition(tombstone.state == "cancelled" && late == tombstone && tombstoneRead == tombstone && !afterLate.contains {$0.date == cancelled.day})
            pass("cancel-before-apply installs durable metadata tombstone; exact late apply never writes")
            let conflict=try mutation(api,sid,first.day,"iOS-R11 stale expected-null"),conflicted=try await api.applyMoodOperation(sessionID:sid,mutation:conflict),conflictCancel=try await api.cancelMoodOperation(sessionID:sid,mutation:conflict)
            precondition(conflicted.state == "conflict" && conflicted.resultUpdatedAt == row.updatedAt && conflictCancel == conflicted)
            let deletion=try mutation(api,sid,first.day,"",record:row,kind:.delete),deleted=try await api.applyMoodOperation(sessionID:sid,mutation:deletion)
            precondition(deleted.state == "applied" && deleted.resultUpdatedAt == row.updatedAt)
            let recreated=try mutation(api,sid,first.day,"iOS-R11 recreated"),recreateReceipt=try await api.applyMoodOperation(sessionID:sid,mutation:recreated),history=try await api.moodOperation(sessionID:sid,mutation:first)
            let recreatedRows=try await api.moods(sessionID:sid)
            precondition(history == created && recreateReceipt.resultUpdatedAt != created.resultUpdatedAt && recreatedRows.first {$0.date == first.day}?.note == recreated.note)
            pass("CAS conflict is HTTP200 terminal; delete token checked; historical applied receipt does not replace recreated current row")
            for offset in 3...5 {
                let race=try mutation(api,sid,String(format:"2026-10-%02d",offset),"iOS-R11 concurrent apply/cancel")
                async let apply=api.applyMoodOperation(sessionID:sid,mutation:race)
                async let cancel=api.cancelMoodOperation(sessionID:sid,mutation:race)
                let (a,c)=try await (apply,cancel),status=try await api.moodOperation(sessionID:sid,mutation:race),current=try await api.moods(sessionID:sid).first {$0.date == race.day}
                precondition(a == c && c == status && ["applied","cancelled"].contains(status.state))
                precondition(status.state == "cancelled" ? current == nil : current?.updatedAt == status.resultUpdatedAt)
            }
            pass("three actual concurrent URLSession apply/cancel races each converge to one terminal receipt and matching current row")
            let same=try mutation(api,sid,"2026-10-06","iOS-R11 concurrent same-ID apply")
            async let a=api.applyMoodOperation(sessionID:sid,mutation:same)
            async let b=api.applyMoodOperation(sessionID:sid,mutation:same)
            let (one,two)=try await (a,b),sameRows=try await api.moods(sessionID:sid)
            precondition(one == two && sameRows.filter {$0.date == same.day}.count == 1 && sameRows.first {$0.date == same.day}?.updatedAt == one.resultUpdatedAt)
            pass("concurrent exact-ID duplicate apply creates one version, both receipts identical")
            let lost=MoodStore(defaults:defaults);await lost.bind(api:api,sessionID:sid,supported:true,ledgerSupported:true);await lost.select(day:"2026-10-07")
            lost.edit(x:0.3,y:0.2,note:"[IOS_R11_DROP_AFTER] synthetic committed-response fault");await lost.save()
            precondition(lost.draft?.pending != nil && !lost.canSave);await lost.refresh()
            precondition(lost.draft?.pending == nil && lost.current?.note.hasPrefix("[IOS_R11_DROP_AFTER]") == true)
            pass("actual MoodStore handles injected HTTP503 after commit: preserved pending resolves by ledger GET and current diary GET")
            await lost.select(day:"2026-10-08");lost.edit(x:0,y:0,note:"[IOS_R11_DROP_BEFORE] synthetic pre-dispatch fault");await lost.save()
            let original=lost.draft!.pending!;await lost.refresh();precondition(lost.draft?.pending == original && lost.draft?.operationState == "not_found")
            await lost.retryOperation();precondition(lost.draft?.pending == nil && lost.current?.note == original.note)
            pass("actual MoodStore not_found stays locked after pre-dispatch503; explicit original-ID retry succeeds without changing payload")
            await lost.select(day:"2026-10-09");lost.edit(x:0,y:0,note:"[IOS_R11_CANCEL_BEFORE] synthetic cancel-intent fault");await lost.save()
            let cancelledOriginal=lost.draft!.pending!;await lost.cancelOperation();precondition(lost.draft?.cancelRequested == true && lost.draft?.pending == cancelledOriginal)
            let resumed=MoodStore(defaults:defaults);await resumed.bind(api:api,sessionID:sid,supported:true,ledgerSupported:true)
            precondition(resumed.draft?.day == "2026-10-09" && resumed.draft?.pending == cancelledOriginal && resumed.draft?.cancelRequested == true && !resumed.canRetryLedger)
            await resumed.retryOperation();precondition(resumed.draft?.pending == cancelledOriginal)
            await resumed.cancelOperation();precondition(resumed.draft?.pending == nil && resumed.draft?.note == cancelledOriginal.note && resumed.canSave)
            let lateCancelled=try await api.applyMoodOperation(sessionID:sid,mutation:cancelledOriginal),afterCancelled=try await api.moods(sessionID:sid)
            precondition(lateCancelled.state == "cancelled" && !afterCancelled.contains {$0.date == cancelledOriginal.day})
            pass("actual MoodStore persists cancel intent across HTTP503/recreation/not_found; no apply retry, repeat metadata cancel then late apply remains cancelled")
            let after=try await api.conversation(),afterBoundary=try await api.boundary(sessionID:sid),afterFollowups=try await api.followups(sessionID:sid)
            let e=JSONEncoder();e.outputFormatting=[.sortedKeys];let prior=try e.encode(before),later=try e.encode(after)
            precondition(prior == later && boundary.revision == afterBoundary.revision && boundary.suppressionRevision == afterBoundary.suppressionRevision && followups.isEmpty && afterFollowups.isEmpty)
            pass("canonical chat/memories, F5 boundary/suppression and followups unchanged; no model or contact requests")
            print("HOST_R11_PASS:",count,"workflow groups; diary and ledger endpoints only for mutations. Disposable service audit follows.")
        } catch {print("HOST_R11_FAIL:",error.localizedDescription);exit(1)}
    }
}
