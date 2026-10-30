import Foundation

/// Actual macOS Foundation URLSession, using only a fresh DB created by
/// run_round9_smoke.py. No model/chat/source/account/device endpoints.
@main struct Round9Smoke {
    static func main() async {
        guard CommandLine.arguments.count == 3,
              CommandLine.arguments[1] == "--fresh-synthetic-service",
              let url=URL(string:CommandLine.arguments[2]), url.host == "127.0.0.1",
              let port=url.port, port != 18789 else {
            print("NOT_RUN: use run_round9_smoke.py with its fresh temporary DB and random loopback port; never the user preview.")
            exit(2)
        }
        do {
            let api=try EchoAPI(baseURL:url.absoluteString)
            let cap=try await api.capabilities()
            for key in ["in_app_recurring_followups","companion_boundaries","bounded_followup_contact","unified_contact_claim"] {precondition(cap.features[key] == true)}
            let snapshot=try await api.conversation(), sid=snapshot.session.id
            let repeated=try await api.conversation()
            precondition(snapshot.session.id == repeated.session.id)
            print("HOST_MAC_URLSESSION_R9: fresh synthetic DB; real HTTP; NOT iOS runtime / device.")
            print("PASS: capability",cap.contractVersion,"and one canonical conversation decoded.")

            let first=try await api.boundary(sessionID:sid)
            precondition(first.hasKnownMode && first.mode == "active" && first.revision == 0)
            let prefix="iOS-R9-HTTP-"+UUID().uuidString
            let now=Date(), due=now.addingTimeInterval(2)
            var calendar=Calendar(identifier:.gregorian);calendar.timeZone=TimeZone(identifier:"UTC")!
            let hour=(calendar.component(.hour,from:now)+2)%24
            let quietStart=String(format:"%02d:00",hour), quietEnd=String(format:"%02d:01",hour)
            let dailyPending=try EchoPendingFollowup(sessionID:sid,content:prefix+" 每日合成任务",date:due,origin:api.baseURL.absoluteString,
                repeatRule:"daily",timeZone:"UTC",quietStart:quietStart,quietEnd:quietEnd,
                allowContact:true,contactWindowMinutes:5,contactTopic:"只询问这条合成任务")
            let daily=try await api.createFollowup(dailyPending)
            precondition(daily.matches(dailyPending) && daily.allowContact == true && daily.contactEligible == false && daily.contactReason == "not_due")
            let paused=try await api.changeFollowup(daily,status:"paused")
            precondition(paused.paused == true)
            let resumed=try await api.changeFollowup(paused,status:"resumed")
            precondition(resumed.paused == false)
            let oncePending=try EchoPendingFollowup(sessionID:sid,content:prefix+" 默认不联系",date:Date().addingTimeInterval(2),origin:api.baseURL.absoluteString,
                repeatRule:"once",timeZone:"UTC",allowContact:false,contactWindowMinutes:30,contactTopic:"默认不主动问")
            let once=try await api.createFollowup(oncePending)
            precondition(once.matches(oncePending) && once.contactReason == "contact_not_allowed")
            print("PASS: full daily/once metadata including timezone, quiet range, consent window/topic decoded; daily pause/resume matched actual receipts.")

            let quiet=try await api.updateBoundary(sessionID:sid,expectedRevision:first.revision,mode:"paused",until:nil,timeZone:"UTC")
            precondition(quiet.revision == 1 && quiet.mode == "paused" && quiet.suppressionRevision > first.suppressionRevision)
            do {
                _ = try await api.updateBoundary(sessionID:sid,expectedRevision:first.revision,mode:"active",until:nil,timeZone:"UTC")
                fatalError("stale boundary revision must conflict")
            } catch let error as EchoAPIError {precondition(error.statusCode == 409)}
            let afterConflict=try await api.boundary(sessionID:sid)
            precondition(afterConflict.revision == quiet.revision && afterConflict.mode == "paused")
            let active=try await api.updateBoundary(sessionID:sid,expectedRevision:quiet.revision,mode:"active",until:nil,timeZone:"UTC")
            precondition(active.revision == 2 && active.suppressionRevision > quiet.suppressionRevision)
            print("PASS: explicit boundary pause, stale CAS 409 with no overwrite, readback and separately confirmed resume. Existing tasks retained.")

            // Only this disposable synthetic service; at most three seconds.
            try await Task.sleep(for:.seconds(3))
            let dueItems=try await api.followups(sessionID:sid)
            guard let dueDaily=dueItems.first(where:{$0.id == daily.id}),let dueOnce=dueItems.first(where:{$0.id == once.id}) else {fatalError("own synthetic tasks missing")}
            precondition(dueDaily.due && dueDaily.isReviewAvailable && dueDaily.contactEligible == false && dueDaily.contactReason == "boundary_changed")
            precondition(dueOnce.due && dueOnce.isReviewAvailable && dueOnce.contactEligible == false && dueOnce.contactReason == "contact_not_allowed")
            let advanced=try await api.changeFollowup(dueDaily,status:"done")
            precondition(advanced.status == "pending" && advanced.confirmsTransition(from:dueDaily,target:"done") && advanced.matches(dailyPending))
            let sameDaily=try await api.createFollowup(dailyPending)
            precondition(sameDaily.id == advanced.id && sameDaily.matches(dailyPending) && sameDaily.dueAt == advanced.dueAt)
            _ = try await api.changeFollowup(advanced,status:"cancelled")
            _ = try await api.changeFollowup(dueOnce,status:"cancelled")
            let final=try await api.followups(sessionID:sid)
            precondition(final.count == 2 && final.allSatisfy {$0.status == "cancelled"})
            print("PASS: due tasks remain reviewable without contact; pause/resume invalidates earlier future consent. Daily completion advances one occurrence; original request reconciles created_due_at; both own tasks cancelled.")
            print("HOST_R9_PASS: 4 workflow groups; no model, contact claim, notification, CLI, credential, source or hardware use.")
        } catch {print("HOST_R9_FAIL:",error.localizedDescription);exit(1)}
    }
}
