import Foundation

/// Actual host URLSession against the root-owned synthetic service only.
/// Never sends /api/chat, reads credentials, or writes memories / sources.
@main struct IncrementalSmoke {
    static func raw(_ path: String, method: String = "GET", body: [String:Any]? = nil) async throws -> [String:Any] {
        var request=URLRequest(url:URL(string:"http://127.0.0.1:18789"+path)!)
        request.httpMethod=method; request.timeoutInterval=15; request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json",forHTTPHeaderField:"Accept")
        if let body {request.setValue("application/json",forHTTPHeaderField:"Content-Type"); request.httpBody=try JSONSerialization.data(withJSONObject:body)}
        let (data,response)=try await URLSession.shared.data(for:request)
        guard let http=response as? HTTPURLResponse, http.statusCode == 200,
              let object=try JSONSerialization.jsonObject(with:data) as? [String:Any] else {throw EchoAPIError.message("Host smoke received incompatible HTTP response for "+path)}
        return object
    }
    static func messageRecords(_ export: [String:Any]) -> [String:Data] {
        Dictionary(uniqueKeysWithValues:(export["messages"] as? [[String:Any]] ?? []).compactMap { row in
            guard let id=row["id"] as? String else {return nil}
            return (id,try! JSONSerialization.data(withJSONObject:row,options:.sortedKeys))
        })
    }
    static func verifyExistingMessages(_ before: [String:Data], _ after: [String:Data]) {
        precondition(before.allSatisfy {after[$0.key] == $0.value},"An existing stored message changed; do not assume which concurrent caller caused it.")
    }
    static func main() async {
        guard CommandLine.arguments.contains("--isolated-synthetic-db") else {
            print("NOT_RUN: requires --isolated-synthetic-db after root confirms 18789 uses only synthetic data.")
            exit(2)
        }
        do {
            let api=try EchoAPI(baseURL:"http://127.0.0.1:18789")
            let metadata=try await api.capabilities()
            precondition(metadata.contractVersion == "1.2.0" && metadata.features["chat_delivery_targeted_stop"] == true)
            let snapshot=try await api.conversation(), sid=snapshot.session.id
            print("HOST_MAC_URLSESSION_INCREMENTAL: actual HTTP to root-owned synthetic service; NOT iOS app / simulator / device.")
            print("Canonical:",sid,"contract:",metadata.contractVersion,"targeted-stop capability:",metadata.features["chat_delivery_targeted_stop"] == true)
            let assistants=snapshot.messages.filter {$0.role == "assistant"}, parts=assistants.filter {$0.bubbles != nil}
            precondition(parts.allSatisfy {$0.displayParts == $0.bubbles! && $0.deliveryPending != nil})
            print("PASS: actual canonical JSON decoded; assistant count:",assistants.count,"messages with bubbles:",parts.count,"pending:",parts.filter {$0.deliveryPending == true}.count)
            if parts.isEmpty {print("NOT_COVERED: no existing bubbles fixture; synthetic Foundation coverage is separate.")}
            let records=try await api.followups(sessionID:sid)
            precondition(records.allSatisfy {$0.repeatRule != nil && $0.paused != nil && $0.quiet != nil && $0.available != nil})
            let daily=records.filter {$0.repeatRule == "daily"}
            precondition(daily.allSatisfy {!$0.supportsNativeTransitions})
            precondition(records.filter {$0.paused == true || $0.quiet == true}.allSatisfy {!$0.isAvailableNow})
            print("PASS: actual followup recurring metadata decoded; records:",records.count,"daily:",daily.count,"paused:",records.filter {$0.paused == true}.count,"quiet:",records.filter {$0.quiet == true}.count)
            if daily.isEmpty {print("NOT_COVERED: no existing daily fixture; this script is authorized to create once only.")}

            let before=messageRecords(try await raw("/api/export?session_id="+sid))
            for body in [nil, [:]] as [[String:Any]?] {
                let response=try await raw("/api/session/"+sid+"/delivery/stop",method:"POST",body:body)
                precondition(response["ok"] as? Bool == true && response["stopped"] as? Bool == false && response["reason"] as? String == "message_id_required")
                verifyExistingMessages(before,messageRecords(try await raw("/api/export?session_id="+sid)))
            }
            let staleID="ios-stale-assistant-"+UUID().uuidString
            let stale=try await api.stopDelivery(sessionID:sid,messageID:staleID)
            precondition(!stale.stopped && stale.messageId == staleID && stale.reason == "not_current")
            verifyExistingMessages(before,messageRecords(try await raw("/api/export?session_id="+sid)))
            print("PASS: no-body / missing-ID / stale-ID stops all returned stopped:false; every pre-existing exported message row unchanged. No claim of cancelling a model or testing an active pending fixture.")

            let prefix="iOS-R8-LIVE-INC-"+UUID().uuidString
            let request=try EchoPendingFollowup(sessionID:sid,content:prefix+" 合成一次跟进，验收后取消",date:Date().addingTimeInterval(900),origin:api.baseURL.absoluteString)
            let created=try await api.createFollowup(request)
            precondition(created.content.hasPrefix(prefix) && created.status == "pending" && created.repeatRule == "once" && created.supportsNativeTransitions)
            let cancelled=try await api.changeFollowup(id:created.id,sessionID:sid,status:"cancelled")
            precondition(cancelled.status == "cancelled")
            let final=try await api.followups(sessionID:sid)
            precondition(final.filter {$0.requestId == request.requestID}.count == 1 && final.first(where:{$0.id == created.id})?.status == "cancelled")
            print("PASS: created and cancelled ONLY own once followup:",created.id,"request:",request.requestID,"prefix:",prefix)
            print("HOST_INCREMENTAL_PASS: capability / JSON decode / three harmless stop variants / own followup create-cancel; no model, credentials, real accounts, sources, memories, hardware, or service restart.")
        } catch {print("HOST_INCREMENTAL_FAIL:",error.localizedDescription); exit(1)}
    }
}
