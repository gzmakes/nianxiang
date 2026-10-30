import Foundation

@main struct Round11LegacyMoodSmoke {
    static func main() async {
        guard CommandLine.arguments.count == 3, CommandLine.arguments[1] == "--fresh-synthetic-service",let url=URL(string:CommandLine.arguments[2]),url.host == "127.0.0.1",let port=url.port,![18787,18789,18791].contains(port) else {print("NOT_RUN: use fresh temporary service runner, never a user preview.");exit(2)}
        do {
            let api=try EchoAPI(baseURL:url.absoluteString),cap=try await api.capabilities()
            precondition(cap.contractVersion == "1.5.0" && cap.features["daily_mood_entries"] == true && cap.features["mood_self_report_suggestions"] == true && cap.features["companion_boundaries"] == true)
            let before=try await api.conversation(),sid=before.session.id
            let boundary=try await api.boundary(sessionID:sid),followups=try await api.followups(sessionID:sid)
            let initial=try await api.moods(sessionID:sid);precondition(initial.isEmpty)
            print("HOST_R11_LEGACY_MOOD: actual macOS Foundation URLSession to fresh temporary DB; NOT iOS SDK / app / device.")
            print("PASS: contract1.5 / new and R9 capability flags; initial canonical, boundary, followups and empty diary decoded.")
            var draft=EchoMoodDraft(origin:api.baseURL.absoluteString,sessionID:sid,day:"2026-10-28")
            draft.x=0.3;draft.y = -0.4;draft.xSelected=true;draft.ySelected=true;draft.dirty=true;draft.note="iOS-R11-LEGACY-"+UUID().uuidString+" 合成手动自述"
            let created=try await api.saveMood(sessionID:sid,mutation:.init(kind:.save,draft:draft))
            let read=try await api.moods(sessionID:sid);precondition(read == [created])
            var edited=EchoMoodDraft(origin:api.baseURL.absoluteString,sessionID:sid,day:draft.day,record:created);edited.note += "，本人修改";edited.dirty=true
            let saved=try await api.saveMood(sessionID:sid,mutation:.init(kind:.save,draft:edited));precondition(saved.updatedAt != created.updatedAt)
            do {_ = try await api.saveMood(sessionID:sid,mutation:.init(kind:.save,draft:edited));fatalError("old version must conflict")} catch let error as EchoAPIError {precondition(error.statusCode == 409)}
            do {try await api.deleteMood(sessionID:sid,mutation:.init(kind:.delete,draft:edited));fatalError("old delete must conflict")} catch let error as EchoAPIError {precondition(error.statusCode == 409)}
            let afterConflict=try await api.moods(sessionID:sid);precondition(afterConflict == [saved])
            print("PASS: actual create/read/edit receipts, stale PUT and DELETE 409 without overwrite or automatic retry.")
            let current=EchoMoodDraft(origin:api.baseURL.absoluteString,sessionID:sid,day:draft.day,record:saved)
            try await api.deleteMood(sessionID:sid,mutation:.init(kind:.delete,draft:current))
            let recreated=try await api.saveMood(sessionID:sid,mutation:.init(kind:.save,draft:draft));precondition(recreated.updatedAt != saved.updatedAt && recreated.updatedAt != created.updatedAt)
            do {_ = try await api.saveMood(sessionID:sid,mutation:.init(kind:.save,draft:current));fatalError("deleted record token cannot overwrite recreated day")} catch let error as EchoAPIError {precondition(error.statusCode == 409)}
            do {try await api.deleteMood(sessionID:sid,mutation:.init(kind:.delete,draft:current));fatalError("deleted token cannot delete recreated day")} catch let error as EchoAPIError {precondition(error.statusCode == 409)}
            let afterRecreate=try await api.moods(sessionID:sid);precondition(afterRecreate == [recreated])
            print("PASS: delete/recreate receives a new opaque ISO token; both stale pre-delete operations rejected and recreated self-report retained.")
            let cleanup=EchoMoodDraft(origin:api.baseURL.absoluteString,sessionID:sid,day:draft.day,record:recreated)
            try await api.deleteMood(sessionID:sid,mutation:.init(kind:.delete,draft:cleanup));let empty=try await api.moods(sessionID:sid);precondition(empty.isEmpty)
            let after=try await api.conversation(),afterBoundary=try await api.boundary(sessionID:sid),afterFollowups=try await api.followups(sessionID:sid)
            let encoder=JSONEncoder();encoder.outputFormatting=[.sortedKeys]
            let beforeData=try encoder.encode(before),afterData=try encoder.encode(after);precondition(beforeData == afterData)
            precondition(boundary.revision == afterBoundary.revision && boundary.mode == afterBoundary.mode && boundary.suppressionRevision == afterBoundary.suppressionRevision)
            precondition(followups.isEmpty && afterFollowups.isEmpty)
            print("PASS: own diary cleaned; canonical chat/memories, F5 boundary and followups unchanged. No automatic chat, memory or contact request.")
            print("HOST_R11_LEGACY_MOOD_PASS: 4 workflow groups; no model, suggestion, account, source, notification, CLI or hardware use.")
        } catch {print("HOST_R11_LEGACY_MOOD_FAIL:",error.localizedDescription);exit(1)}
    }
}
