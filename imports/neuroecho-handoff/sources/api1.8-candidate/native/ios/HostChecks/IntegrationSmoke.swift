import Foundation

/// Run only against the root-created synthetic-data service, never the user DB.
@main struct IntegrationSmoke {
    static func main() async {
        guard CommandLine.arguments.contains("--isolated-synthetic-db") else {
            print("NOT_RUN: pass --isolated-synthetic-db only after confirming 127.0.0.1:18789 is an isolated test DB. This script writes its own synthetic memory and followups.")
            exit(2)
        }
        do {
            let api = try EchoAPI(baseURL:"http://127.0.0.1:18789")
            let metadata = try await api.capabilities()
            precondition(metadata.features["memory_expected_version_patch"] == true)
            let snapshot = try await api.conversation(), sid = snapshot.session.id
            print("HOST_MAC_URLSESSION_ONLY: isolated synthetic service; no model, real account, file or hardware use.")
            print("Canonical:",sid,"contract:",metadata.contractVersion)
            let memory = try await api.addMemory(sessionID:sid,text:"iOS 宿主验收合成记忆：希望回复简短。")
            precondition(memory.status == "candidate")
            print("Created own synthetic memory:",memory.id,"version:",memory.version)
            let updated = try await api.updateMemory(id:memory.id,text:"iOS 宿主验收合成记忆：希望回复两段。",expectedVersion:memory.version)
            precondition(updated.version == memory.version + 1)
            do {_ = try await api.updateMemory(id:memory.id,text:"不应覆盖的旧版本",expectedVersion:memory.version); fatalError("stale PATCH must conflict")}
            catch let error as EchoAPIError {precondition(error.statusCode == 409)}
            do {try await api.deleteMemory(id:memory.id,expectedVersion:memory.version); fatalError("stale DELETE must conflict")}
            catch let error as EchoAPIError {precondition(error.statusCode == 409)}
            let reconciled = try await api.conversation()
            precondition(reconciled.memories.first(where:{$0.id == memory.id})?.text == updated.text)
            try await api.deleteMemory(id:memory.id,expectedVersion:updated.version)
            print("PASS: actual CAS edit + stale PATCH/DELETE 409 + refresh + exact-version delete; removed only this own synthetic memory.")

            let first = try EchoPendingFollowup(sessionID:sid,content:"iOS 宿主合成跟进：核对同一请求",date:Date().addingTimeInterval(600),origin:api.baseURL.absoluteString)
            let created = try await api.createFollowup(first)
            let repeated = try await api.createFollowup(first)
            precondition(created.id == repeated.id)
            let records = try await api.followups(sessionID:sid)
            precondition(records.filter {$0.requestId == first.requestID}.count == 1)
            let done = try await api.changeFollowup(id:created.id,sessionID:sid,status:"done")
            precondition(done.status == "done")
            do {_ = try await api.changeFollowup(id:created.id,sessionID:sid,status:"cancelled"); fatalError("terminal transition must conflict")}
            catch let error as EchoAPIError {precondition(error.statusCode == 409)}
            print("PASS: same request returns same followup:",created.id,"final status: done; conflicting terminal transition rejected.")

            let second = try EchoPendingFollowup(sessionID:sid,content:"iOS 宿主合成跟进：验证取消",date:Date().addingTimeInterval(600),origin:api.baseURL.absoluteString)
            let cancellable = try await api.createFollowup(second)
            let cancelled = try await api.changeFollowup(id:cancellable.id,sessionID:sid,status:"cancelled")
            precondition(cancelled.status == "cancelled")
            print("PASS: explicit cancel:",cancellable.id,"final status: cancelled.")
            print("HOST_SMOKE_PASS: 3 workflow groups; no iOS app / simulator / device validation.")
        } catch {print("HOST_SMOKE_FAIL:",error.localizedDescription); exit(1)}
    }
}
