package cn.xinji.echo

import java.time.Instant
import kotlinx.coroutines.runBlocking

/** Runs the actual native HTTP/JSON client against an isolated real backend. */
fun main(args: Array<String>) = runBlocking {
    val api = EchoApi(args[0])
    var checks = 0
    fun verify(condition: Boolean, label: String) { check(condition) { label }; checks++ }
    val features = api.get("/api/capabilities").getJSONObject("features")
    verify(features.getBoolean("in_app_one_time_followups"), "backend follow-up capability")
    val current = conversation(api.get("/api/conversation"))
    verify(current.id.isNotEmpty(), "canonical conversation")
    verify(features.getBoolean("chat_delivery_targeted_stop"), "server explicitly supports targeted stop before mutation")
    val oldMessageId = args[1]; val latestMessageId = args[2]
    val pendingDelivery = current.messages.single { it.id == latestMessageId }
    val deliveryAttempt = DeliveryStopAttempt(args[0], current.id, latestMessageId)
    verify(pendingDelivery.deliveryPending && deliveryAttempt.canStart(true, args[0], current), "latest synthetic assistant is pending and targetable")
    val noId = api.post("/api/session/${encoded(current.id)}/delivery/stop", json())
    verify(noId.opt("stopped") == false && noId.str("reason") == "message_id_required", "no target is a non-mutating false receipt")
    val oldAttempt = deliveryAttempt.copy(messageId = oldMessageId)
    val oldRequest = oldAttempt.request()
    val staleStop = api.post(oldRequest.path, oldRequest.body)
    verify(staleStop.opt("stopped") == false && staleStop.str("reason") == "not_current", "late old target cannot stop latest delivery")
    verify(conversation(api.get("/api/conversation")).messages.single { it.id == latestMessageId }.deliveryPending, "latest delivery survives missing and stale IDs")
    val deliveryRequest = deliveryAttempt.request()
    val deliveryReceipt = api.post(deliveryRequest.path, deliveryRequest.body)
    verify(deliveryAttempt.receiptMatches(deliveryReceipt), "exact target has explicit true stopped receipt")
    val stoppedDelivery = conversation(api.get("/api/conversation"))
    verify(deliveryAttempt.reconciled(deliveryReceipt, stoppedDelivery), "GET confirms exact target stopped")
    val repeatedStop = api.post(deliveryRequest.path, deliveryRequest.body)
    verify(repeatedStop.opt("stopped") == false && repeatedStop.str("reason") == "not_pending", "already stopped delivery does not claim another success")
    verify(stoppedDelivery.messages.single { it.id == latestMessageId }.displayParts == listOf("合成新首段"), "only previously visible text retained after stop")
    val raw = current.messages.single { it.role == "user" }
    val rawReview = quoteReview(raw, current)!!
    val quote = quoteRequest(rawReview)
    val rejected = try { api.post(quote.path, quote.body); null } catch (error: ApiError) { error }
    verify(rejected?.status == 409, "ordinary non-allowlisted quote is explicitly rejected")
    verify(conversation(api.get("/api/conversation")).memories.none { it.text == raw.text }, "409 did not automatically save the quote")
    val fallback = quoteReviewAfterRejection(raw, current, rejected!!.status)!!
    verify(fallback.text == raw.text, "manual review preserves exact original text")
    val manual = manualMemoryRequest(fallback.candidate(current), current.id)
    verify(!manual.body.has("confirm") && !manual.body.has("status"), "explicit second operation does not auto-confirm memory")
    val candidate = memory(api.post(manual.path, manual.body))
    verify(candidate.status == "candidate" && candidate.text == raw.text && candidate.source == "用户手动添加" && candidate.sourceMessageId.isEmpty(), "only explicit manual save creates unconfirmed candidate")
    verify(conversation(api.get("/api/conversation")).memories.any { it.id == candidate.id && it.status == "candidate" }, "candidate remains unconfirmed in canonical data")
    val draft = FollowupDraft(current.id, "合成验证：明天再看一眼", Instant.now().plusSeconds(7200).toString()).prepared()
    val first = followup(api.post("/api/followups", draft.body()))
    verify(first.sessionId == current.id && first.requestId == draft.requestId && first.status == "pending", "exact persisted create receipt")
    val retry = followup(api.post("/api/followups", draft.body()))
    verify(retry.id == first.id, "same request does not create another follow-up")
    val records = followups(api.get("/api/followups?session_id=${encoded(current.id)}"))
    verify(records.count { it.requestId == draft.requestId } == 1, "one row after retry")
    verify(draft.matching(records)?.id == first.id, "lost-result reconciliation uses matching request and payload")
    val change = followupTransitionRequest(first, "cancelled")
    val cancelled = followup(api.post(change.path, change.body))
    verify(cancelled.id == first.id && cancelled.status == "cancelled" && !cancelled.due, "real POST transition cancels the exact row")
    val again = followup(api.post(change.path, change.body))
    verify(again.id == first.id && again.status == "cancelled", "same terminal transition is idempotent")
    val conflict = followupTransitionRequest(first, "done")
    val error = try { api.post(conflict.path, conflict.body); null } catch (value: ApiError) { value }
    verify(error?.status == 409 && error.code == "followup_conflict", "terminal conflict is unresolved, not success")
    val final = followups(api.get("/api/followups?session_id=${encoded(current.id)}"))
    verify(final.single { it.id == first.id }.status == "cancelled", "final persisted cancellation")
    // These sources contain only the visible synthetic strings below. The
    // local-file confirmation route does not invoke a CLI or a model service.
    fun localFile(name: String, text: String) = json("session_id" to current.id, "files" to org.json.JSONArray(listOf(json("name" to name, "text" to text))))
    val withA = conversation(api.post("/api/local-files/confirm", localFile("synthetic-a.txt", "合成资料A，只用于撤回验收。")))
    verify(withA.id == current.id && withA.sources.size == 1, "first synthetic source attached to canonical conversation")
    val sourceA = withA.sources.single()
    val withB = conversation(api.post("/api/local-files/confirm", localFile("synthetic-b.txt", "合成资料B，撤回A后应保留。")))
    verify(withB.sources.size == 2, "independent synthetic source B attached")
    val sourceB = withB.sources.single { it.id != sourceA.id }
    val revoke = SourceRevocationAttempt(args[0], current.id, sourceA)
    verify(revoke.canStart(args[0], withB), "approval bound to exact current source snapshot")
    val revokeReceipt = api.post("/api/source/revoke", revoke.body())
    verify(revoke.receiptMatches(revokeReceipt), "explicit true receipt contains exact source id and known state")
    val afterRevoke = conversation(api.get("/api/conversation"))
    verify(revoke.outcome(revokeReceipt, afterRevoke, args[0], current.id, revoke.token) == SourceRevokeOutcome.CONFIRMED, "same-context read confirms selected source disappeared")
    verify(afterRevoke.sources.map { it.id } == listOf(sourceB.id), "unrelated source B is retained")
    val missing = try { api.post("/api/source/revoke", revoke.body()); null } catch (value: ApiError) { value }
    verify(missing?.status == 404, "already-absent source is not reported as another successful withdrawal")
    verify(revoke.outcome(null, afterRevoke, args[0], current.id, revoke.token) == SourceRevokeOutcome.UNRESOLVED, "missing receipt alone cannot produce a success claim")
    verify(conversation(api.get("/api/conversation")).sources.map { it.id } == listOf(sourceB.id), "failed second withdrawal never removes source B")

    verify(features.opt("in_app_recurring_followups") == true && features.opt("companion_boundaries") == true && features.opt("bounded_followup_contact") == true, "R9 optional capabilities explicit")
    var boundary = companionBoundary(api.get("/api/companion-boundary?session_id=" + encoded(current.id)))
    val pause = boundaryChange(current.id, boundary, "paused")
    boundary = companionBoundary(api.put("/api/companion-boundary", pause.body()))
    verify(pause.matches(boundary) && boundary.isPaused, "explicit CAS pause persists")
    verify(companionBoundary(api.get("/api/companion-boundary?session_id=" + encoded(current.id))) == boundary, "second HTTP read sees same boundary")
    val staleBoundary = try { api.put("/api/companion-boundary", pause.body()); null } catch (error: ApiError) { error }
    verify(staleBoundary?.status == 409 && staleBoundary.code == "boundary_conflict", "old boundary revision cannot overwrite current preference")
    val resume = boundaryChange(current.id, boundary, "active")
    boundary = companionBoundary(api.put("/api/companion-boundary", resume.body()))
    verify(resume.matches(boundary), "explicit resume has checked receipt")
    val dailyDraft = FollowupDraft(current.id, "合成R9每日跟进", Instant.now().plusSeconds(7200).toString(),
        repeatRule = "daily", timeZone = "Asia/Shanghai", quietStart = "22:00", quietEnd = "08:00",
        contactFieldsIncluded = true).prepared()
    val daily = followup(api.post("/api/followups", dailyDraft.body()))
    verify(dailyDraft.matching(listOf(daily)) != null && daily.repeatRule == "daily", "new daily full payload and created_due_at reconcile")
    verify(followup(api.post("/api/followups", dailyDraft.body())).id == daily.id, "daily same ID retry never creates another item")
    val pauseDaily = followupTransitionRequest(daily, "paused")
    val pausedDaily = followup(api.post(pauseDaily.path, pauseDaily.body))
    verify(followupTransitionMatches(daily, "paused", pausedDaily), "daily pause checks exact receipt")
    val resumeDaily = followupTransitionRequest(pausedDaily, "resumed")
    val resumedDaily = followup(api.post(resumeDaily.path, resumeDaily.body))
    verify(followupTransitionMatches(pausedDaily, "resumed", resumedDaily), "daily resume checks exact receipt")
    val cancelDaily = followupTransitionRequest(resumedDaily, "cancelled")
    verify(followupTransitionMatches(resumedDaily, "cancelled", followup(api.post(cancelDaily.path, cancelDaily.body))), "daily cancellation remains terminal")
    val nextHour = Instant.now().atZone(java.time.ZoneId.of("UTC"))
    val policy = api.get("/api/followup-notification-settings?session_id=" + encoded(current.id))
    api.put("/api/followup-notification-settings", json("session_id" to current.id, "expected_revision" to policy.getInt("revision"),
        "enabled" to false, "time_zone" to "UTC",
        "quiet_start" to nextHour.plusHours(6).format(java.time.format.DateTimeFormatter.ofPattern("HH:mm")),
        "quiet_end" to nextHour.plusHours(7).format(java.time.format.DateTimeFormatter.ofPattern("HH:mm")),
        "cooldown_minutes" to 60, "daily_limit" to 3, "pause_until" to null))
    val contactDraft = FollowupDraft(current.id, "合成窗口，绝不调用系统通知", Instant.now().plusSeconds(1).toString(),
        timeZone = "UTC", allowContact = true, contactWindowMinutes = 5, contactTopic = "R9边界",
        contactFieldsIncluded = true).prepared()
    val contact = followup(api.post("/api/followups", contactDraft.body()))
    verify(contactDraft.matching(listOf(contact)) != null, "bounded consent and topic echo exactly")
    Thread.sleep(1200)
    val claimBody = json("session_id" to current.id, "occurrence_at" to contact.dueAt, "channel" to "in_app")
    val claim = api.post("/api/followups/" + encoded(contact.id) + "/contact/claim", claimBody)
    verify(claim.opt("claimed") == true && claim.str("claim_id").isNotEmpty(), "in-app permission atomically claimed, no UI or OS invocation")
    val duplicate = api.post("/api/followups/" + encoded(contact.id) + "/contact/claim", claimBody)
    verify(duplicate.opt("claimed") == false, "repeat claim cannot trigger second contact")
    val latePause = boundaryChange(current.id, boundary, "paused")
    boundary = companionBoundary(api.put("/api/companion-boundary", latePause.body()))
    val recheckPath = "/api/followup-contacts/" + encoded(claim.str("claim_id")) + "/recheck"
    verify(api.post(recheckPath, json("session_id" to current.id)).opt("allowed") == false, "refusal invalidates reserved contact before presentation")
    val lateResume = boundaryChange(current.id, boundary, "active")
    boundary = companionBoundary(api.put("/api/companion-boundary", lateResume.body()))
    verify(api.post(recheckPath, json("session_id" to current.id)).opt("allowed") == false, "resume never resurrects old reservation")
    val lateFinish = try { api.post("/api/followup-contacts/" + encoded(claim.str("claim_id")) + "/finish", json("session_id" to current.id, "state" to "submitted")); null } catch (error: ApiError) { error }
    verify(lateFinish?.status == 409 && lateFinish.code == "contact_conflict", "late completion cannot claim presentation after boundary change")
    verify(conversation(api.get("/api/conversation")).id == current.id, "all controls preserve the same canonical conversation")
    verify(features.opt("daily_mood_entries") == true, "R10 diary capability explicit")
    val moodListPath = "/api/moods?session_id=" + encoded(current.id)
    verify(moodRecords(api.get(moodListPath)).isEmpty(), "fresh diary starts empty, no inferred records")
    val moodDraft = MoodDraft(current.id, "2026-10-30", .3, -.4, "合成本人原话", true, true)
    val denied = try { api.put("/api/moods/" + moodDraft.date, moodDraft.body().put("confirmed", false)); null } catch (error: ApiError) { error }
    verify(denied?.status == 400 && denied.code == "confirmation_required", "diary requires explicit confirmation")
    verify(moodRecords(api.get(moodListPath)).isEmpty(), "unconfirmed save has no record")
    val savedMood = moodRecord(api.put("/api/moods/" + moodDraft.date, moodDraft.body()))
    verify(moodDraft.matches(savedMood), "actual Kotlin PUT receipt matches day, both coordinates and note")
    verify(moodRecords(api.get(moodListPath)) == listOf(savedMood), "GET reconciles exact persisted diary")
    val staleSave = try { api.put("/api/moods/" + moodDraft.date, moodDraft.body()); null } catch (error: ApiError) { error }
    verify(staleSave?.status == 409 && staleSave.code == "mood_conflict", "lost-result same create cannot overwrite existing record")
    val editedDraft = MoodDraft.from(current.id, savedMood.date, savedMood).copy(note = "合成纠正后的原话", dirty = true)
    val editedMood = moodRecord(api.put("/api/moods/" + editedDraft.date, editedDraft.body()))
    verify(editedDraft.matches(editedMood) && editedMood.updatedAt != savedMood.updatedAt, "explicit correction uses read version and returns new token")
    val moodDeleteBase = "/api/moods/" + moodDraft.date + "?session_id=" + encoded(current.id) + "&expected_updated_at="
    val staleDelete = try { api.call("DELETE", moodDeleteBase + encoded(savedMood.updatedAt)); null } catch (error: ApiError) { error }
    verify(staleDelete?.status == 409 && staleDelete.code == "mood_conflict", "stale delete cannot remove newer correction")
    verify(moodRecords(api.get(moodListPath)) == listOf(editedMood), "failed delete preserves exact newer note")
    verify(api.call("DELETE", moodDeleteBase + encoded(editedMood.updatedAt)).opt("deleted") == true, "exact-version delete has strict true receipt")
    verify(moodRecords(api.get(moodListPath)).isEmpty(), "successful deletion followed by explicit absence read")
    val recreatedMood = moodRecord(api.put("/api/moods/" + moodDraft.date, moodDraft.body()))
    verify(recreatedMood.updatedAt != editedMood.updatedAt && recreatedMood.updatedAt != savedMood.updatedAt, "recreate never reuses older version tokens")
    val oldDelete = try { api.call("DELETE", moodDeleteBase + encoded(editedMood.updatedAt)); null } catch (error: ApiError) { error }
    verify(oldDelete?.status == 409, "old delete after recreate remains rejected")
    verify(conversation(api.get("/api/conversation")).memories.none { it.text.contains("合成本人原话") }, "diary never automatically becomes memory or chat")
    api.call("DELETE", moodDeleteBase + encoded(recreatedMood.updatedAt))
    verify(moodRecords(api.get(moodListPath)).isEmpty(), "only synthetic mood removed at end")
    verify(features.opt("mood_operation_ledger") == true, "R11 mutation ledger capability explicit")
    val ledgerDraft = moodDraft.copy(note = "合成R11🙂\n冻结原文").beginSave(true)
    val operation = ledgerDraft.ledgerOperation()!!
    val opPath = "/api/mood-operations/" + encoded(operation.requestId)
    fun receipt(obj: org.json.JSONObject) = moodOperationReceipt(obj, current.id, operation)
    verify(receipt(api.get(opPath + "?session_id=" + encoded(current.id))).state == "not_found", "not_found is only current observation")
    val applied = receipt(api.post("/api/mood-operations", operation.applyBody(current.id)))
    verify(applied.state == "applied", "actual raw JSON apply with identity has checked terminal receipt")
    val ledgerSaved = moodRecords(api.get(moodListPath)).single()
    verify(ledgerSaved.note == ledgerDraft.note && ledgerSaved.updatedAt == applied.resultUpdatedAt, "separate current GET verifies exact note and issued version")
    val restored = MoodDraft.decode(ledgerDraft.encode())!!
    verify(receipt(api.post("/api/mood-operations", restored.ledgerOperation()!!.applyBody(current.id))) == applied, "restored raw request and ID retry returns identical receipt")
    verify(moodRecords(api.get(moodListPath)).single() == ledgerSaved, "retry never rewrites timestamp")
    val changedIdentity = MoodOperation(operation.requestId, operation.raw + " ", "save")
    val changedError = try { api.post("/api/mood-operations", changedIdentity.applyBody(current.id)); null } catch (error: ApiError) { error }
    verify(changedError?.status == 409 && changedError.code == "mood_operation_identity_conflict", "same ID changed exact bytes is identity conflict")
    val cancelTooLate = receipt(api.post(opPath + "/cancel", operation.cancelBody(current.id)))
    verify(cancelTooLate == applied, "cancel after apply returns applied and never rollback")
    verify(moodRecords(api.get(moodListPath)).single() == ledgerSaved, "late cancellation preserves existing row")
    api.call("DELETE", moodDeleteBase + encoded(ledgerSaved.updatedAt))
    verify(moodRecords(api.get(moodListPath)).isEmpty(), "later explicit deletion removes current note")
    verify(receipt(api.post("/api/mood-operations", operation.applyBody(current.id))) == applied, "old save replay returns historical metadata only")
    verify(moodRecords(api.get(moodListPath)).isEmpty(), "historical successful replay cannot resurrect deleted private note")
    val cancelledDraft = moodDraft.copy(note = "合成R11预取消").beginSave(true).requestCancellation()
    val cancelledOp = cancelledDraft.ledgerOperation()!!
    val cancelledPath = "/api/mood-operations/" + encoded(cancelledOp.requestId)
    val cancelledReceipt = moodOperationReceipt(api.post(cancelledPath + "/cancel", cancelledOp.cancelBody(current.id)), current.id, cancelledOp)
    verify(cancelledReceipt.state == "cancelled", "pre-cancel creates durable terminal tombstone")
    verify(moodOperationReceipt(api.post("/api/mood-operations", cancelledOp.applyBody(current.id)), current.id, cancelledOp) == cancelledReceipt, "late exact POST cannot pass cancelled tombstone")
    verify(moodRecords(api.get(moodListPath)).isEmpty(), "late cancelled save created no row")
    verify(moodOperationReceipt(api.get(cancelledPath + "?session_id=" + encoded(current.id)), current.id, cancelledOp).state == "cancelled", "GET reconciles durable cancellation metadata")
    verify(MoodDraft.decode(cancelledDraft.encode())!!.cancelRequested, "cancel intent survives actual app draft encoding")
    verify(conversation(api.get("/api/conversation")).messages.none { it.text.contains("合成R11") } && conversation(api.get("/api/conversation")).memories.none { it.text.contains("合成R11") }, "ledger content never automatically becomes chat or memory")
    println("HOST_BACKEND_HTTP_OK: $checks checks; real Kotlin EchoApi to isolated FastAPI/SQLite. NOT Android runtime, SDK build or device verification.")
}
