import Foundation

public struct EchoSession: Codable, Identifiable, Sendable {
    public let id: String
    public let mode: String?
    public let sourceLabel: String?
}
public struct EchoMessage: Codable, Identifiable, Sendable {
    public let id: String
    public let role: String
    public let text: String
    public let createdAt: String?
    public let bubbles: [String]?
    public let deliveryPending: Bool?
    public let deliveryNextMs: Int?
    public var displayParts: [String] {
        guard role == "assistant", let parts = bubbles, !parts.isEmpty else {return [text]}
        return parts
    }
}
public struct EchoMemory: Codable, Identifiable, Sendable {
    public let id: String
    public let kind: String
    public let text: String
    public let status: String
    public let version: Int
    public let source: String
    public let sourceAttachmentId: String?
    public let sourceMessageId: String?
    public let createdAt: String?
    public let updatedAt: String?
    public var provenance: String {
        if kind == "inference" && status != "confirmed" { return "推测 · 待你确认" }
        if sourceMessageId != nil || source.contains("对话") { return "你的原话" }
        if sourceAttachmentId != nil { return "来自你选定的文档" }
        return source.isEmpty ? "来源待核对" : source
    }
}
public struct EchoRevision: Codable, Identifiable, Sendable {
    public let id: String
    public let version: Int
    public let text: String
    public let status: String
    public let source: String
    public let createdAt: String?
}
public struct EchoBookmark: Codable, Identifiable, Sendable {
    public let id: String
    public let note: String
    public let nextStep: String?
    public let status: String?
}
public struct EchoSourceItem: Codable, Sendable {
    public let title: String
    public let summary: String?
    public let meta: String?
}
public struct EchoSource: Codable, Identifiable, Sendable {
    public let id: String
    public let connectorId: String?
    public let label: String
    public let title: String?
    public let items: [EchoSourceItem]?
    public let stale: Bool?
    public var displayTitle: String { title ?? items?.first?.title ?? label }
}
public struct EchoContext: Codable, Sendable { public let sources: [EchoSource]? }
public struct EchoConversation: Codable, Sendable {
    public let session: EchoSession
    public let messages: [EchoMessage]
    public let memories: [EchoMemory]
    public let bookmark: EchoBookmark?
    public let context: EchoContext?
}
public struct EchoAction: Codable, Identifiable, Sendable {
    public let id: String
    public let sessionId: String?
    public let kind: String
    public let title: String
    public let detail: String?
    public let status: String
    public let whenText: String?
    public let real: Int?
    public var statusLabel: String {
        switch status {
        case "previewed": return "待你确认"
        case "unknown", "executing": return "结果待核对 · 不会自动重试"
        case "failed": return "未能完成"
        case "committed": return kind == "message" ? "草稿已保存 · 未发送" : real == 1 ? "已写入 Mac 系统" : "已保存到回响服务 · 未写入系统"
        default: return "结果待核对 · 不会自动重试"
        }
    }
}
public struct EchoCatalogSource: Codable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let blurb: String
    public let status: String
    public let hint: String?
    public let reads: [String]?
}
public struct EchoPreview: Codable, Sendable {
    public let ok: Bool
    public let previewId: String?
    public let title: String?
    public let preview: String?
    public let length: Int?
    public let extractedLength: Int?
    public let truncated: Bool?
    public let items: [EchoSourceItem]?
    public let error: String?
    public let hint: String?
    public let understanding: EchoUnderstanding?
    public var hasReviewableContent: Bool {
        if !(preview ?? "").trimmingCharacters(in:.whitespacesAndNewlines).isEmpty {return true}
        return (items ?? []).contains { !$0.title.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || !($0.summary ?? "").trimmingCharacters(in:.whitespacesAndNewlines).isEmpty }
    }
    /// Feishu's preview must be the complete bounded snapshot the service will attach.
    /// Lengths are Unicode scalar counts, matching Python's len and Web's code points.
    public var feishuPreviewScope: String? {
        guard let text = preview, !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty,
              let length, let extractedLength, let truncated,
              length == text.unicodeScalars.count, length <= 12_000,
              extractedLength >= length, truncated == (extractedLength > length) else { return nil }
        return truncated
            ? "已提取 \(extractedLength) 字，以下为将保留的前 \(length) 字；其余内容不会接入。"
            : "以下为将接入的全部 \(length) 字。"
    }
    public func requireID(for sourceID: String? = nil) throws -> String {
        guard ok, let id = previewId, !id.isEmpty, hasReviewableContent else {
            throw EchoAPIError.message([error ?? "没有取得可确认的预览", hint].compactMap { $0 }.joined(separator: " · "))
        }
        if sourceID == "feishu", feishuPreviewScope == nil {
            throw EchoAPIError.message("无法完整核对将接入的飞书正文。请更新电脑上的回响服务并重新读取；本次不会接入。")
        }
        return id
    }
}
public struct EchoUnderstanding: Codable, Sendable {
    public let facts: [String]?
    public let inferences: [String]?
    public let questions: [String]?
}
public struct EchoCapabilities: Codable, Sendable {
    public let contractVersion: String
    public let deploymentMode: String
    public let servicePlatform: String
    public let features: [String:Bool]
    public let platformStatus: [String:String]
    public let connectionStatus: String
}
public struct EchoNextStep: Codable, Sendable { public let step: String?; public let rationale: String? }
public struct EchoDeliveryStop: Codable, Sendable {
    public let ok: Bool
    public let stopped: Bool
    public let messageId: String?
    public let reason: String
    public func confirms(_ messageID: String) -> Bool { ok && stopped && messageId == messageID && reason == "stopped" }
}
public struct EchoFollowup: Codable, Identifiable, Sendable {
    public let id: String
    public let sessionId: String
    public let requestId: String
    public let content: String
    public let dueAt: String
    public let status: String
    public let due: Bool
    public let repeatRule: String?
    public let paused: Bool?
    public let quiet: Bool?
    public let available: Bool?
    public let createdAt: String?
    public let updatedAt: String?
    public let lastOccurrenceAt: String?
    public let createdDueAt: String?
    public let timeZone: String?
    public let quietStart: String?
    public let quietEnd: String?
    public let allowContact: Bool?
    public let contactWindowMinutes: Int?
    public let contactTopic: String?
    public let contactExpiresAt: String?
    public let contactEligible: Bool?
    public let contactReason: String?
    public let reviewAvailable: Bool?
    public let boundaryRevision: Int?
    /// Older services without repeat_rule supported one-time follow-ups only.
    public var supportsNativeTransitions: Bool { repeatRule == nil || ["once","daily"].contains(repeatRule!) }
    public func confirmsTransition(from previous: EchoFollowup, target: String) -> Bool {
        guard id == previous.id, sessionId == previous.sessionId, (repeatRule ?? "once") == (previous.repeatRule ?? "once") else {return false}
        switch target {
        case "paused": return status == "pending" && paused == true
        case "resumed": return status == "pending" && paused == false
        case "cancelled": return status == "cancelled"
        case "done":
            if previous.repeatRule == "daily" {
                guard status == "pending", let last=EchoFollowup.parse(lastOccurrenceAt), let next=date else {return false}
                return last == previous.date && next > last
            }
            return status == "done"
        default: return false
        }
    }
    public var isAvailableNow: Bool { status == "pending" && due && paused != true && quiet != true && (available ?? true) && (contactEligible ?? true) && (allowContact ?? true) }
    /// Passive task viewing never consumes or invents permission to contact.
    public var isReviewAvailable: Bool { status == "pending" && due && paused != true && quiet != true && (reviewAvailable ?? true) }
    public var contactLabel: String {
        guard allowContact == true else {return "未同意主动联系"}
        switch contactReason {
        case "boundary_paused","boundary_until","suppressed_occurrence","boundary_changed":return "主动联系已暂停或这次机会已失效"
        case "expired","claim_expired":return "联系窗口已过，不会补发"
        case "not_due":return "尚未到约定窗口"
        case "item_quiet","quiet","item_paused","paused":return "当前处于安静或暂停时段"
        case "daily_limit","cooldown":return "当前需要留出安静间隔"
        case "already_claimed","topic_window_claimed":return "这次联系机会已使用，不会重复"
        case "completed":return "跟进已处理"
        case nil: return contactEligible == true ? "约定窗口有效，实际呈现仍须统一许可" : "当前未确认联系许可"
        default:return "联系许可待核对，不会自动联系"
        }
    }
    public var statusLabel: String {
        switch status { case "pending":return due ? "已到时间 · 待你回应" : "待跟进"; case "done":return "已完成"; case "cancelled":return "已取消"; default:return "状态待核对" }
    }
    public var date: Date? {
        Self.parse(dueAt)
    }
    public static func parse(_ text: String?) -> Date? {
        guard let text else {return nil}
        let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime,.withFractionalSeconds]
        return formatter.date(from:text) ?? ISO8601DateFormatter().date(from:text)
    }
    public func matches(_ pending: EchoPendingFollowup) -> Bool {
        guard sessionId == pending.sessionID, requestId == pending.requestID, content == pending.content,
              let requestedDate=Self.parse(pending.dueAt) else {return false}
        if pending.repeatRule == nil && (repeatRule ?? "once") != "once" {return false}
        if let rule=pending.repeatRule, repeatRule != rule {return false}
        if let zone=pending.timeZone, timeZone != zone {return false}
        if pending.repeatRule != nil && (quietStart != pending.quietStart || quietEnd != pending.quietEnd) {return false}
        if let allowed=pending.allowContact, allowContact != allowed {return false}
        if let window=pending.contactWindowMinutes, contactWindowMinutes != window {return false}
        if let topic=pending.contactTopic, contactTopic != topic {return false}
        // A daily occurrence may already have advanced on another renderer.
        return (pending.repeatRule == "daily" ? Self.parse(createdDueAt) : date) == requestedDate
    }
    public var hasKnownStatus: Bool { ["pending","done","cancelled"].contains(status) }
}
public struct EchoPendingFollowup: Codable, Sendable {
    public let sessionID: String
    public let content: String
    public let dueAt: String
    public let requestID: String
    public let origin: String
    // Optional fields distinguish old pending payloads; decoding an old record
    // never silently adds new parameters to an uncertain request.
    public let repeatRule: String?
    public let timeZone: String?
    public let quietStart: String?
    public let quietEnd: String?
    public let allowContact: Bool?
    public let contactWindowMinutes: Int?
    public let contactTopic: String?
    public init(sessionID: String, content: String, date: Date, origin: String, requestID: String = UUID().uuidString, now: Date = Date(), repeatRule: String? = nil, timeZone: String? = nil, quietStart: String? = nil, quietEnd: String? = nil, allowContact: Bool? = nil, contactWindowMinutes: Int? = nil, contactTopic: String? = nil) throws {
        let content = content.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !content.isEmpty, content.unicodeScalars.count <= 1000, date > now else {throw EchoAPIError.message("请填写1–1000字，并选择未来时间。")}
        guard repeatRule == nil || ["once","daily"].contains(repeatRule!), timeZone == nil || TimeZone(identifier:timeZone!) != nil else {throw EchoAPIError.message("请核对重复规则和有效的 IANA 时区。")}
        func validClock(_ text: String) -> Bool {let parts=text.split(separator:":",omittingEmptySubsequences:false); return text.count == 5 && parts.count == 2 && (Int(parts[0]).map {(0...23).contains($0)} ?? false) && (Int(parts[1]).map {(0...59).contains($0)} ?? false)}
        if quietStart != nil || quietEnd != nil {guard let start=quietStart, let end=quietEnd, validClock(start),validClock(end),start != end else {throw EchoAPIError.message("安静时段请使用不同的 HH:mm 起止时间。")}}
        let topic=contactTopic?.trimmingCharacters(in:.whitespacesAndNewlines)
        guard contactWindowMinutes == nil || (5...180).contains(contactWindowMinutes!), topic == nil || (!topic!.isEmpty && topic!.unicodeScalars.count <= 1000) else {throw EchoAPIError.message("联系窗口应为5–180分钟，话题应为1–1000字。")}
        let formatter = ISO8601DateFormatter(); formatter.timeZone = TimeZone(secondsFromGMT:0)
        self.sessionID = sessionID; self.content = content; self.dueAt = formatter.string(from:date); self.requestID = requestID; self.origin = origin
        self.repeatRule=repeatRule; self.timeZone=timeZone; self.quietStart=quietStart; self.quietEnd=quietEnd
        self.allowContact=allowContact; self.contactWindowMinutes=contactWindowMinutes; self.contactTopic=topic
    }
    public var body: [String:Any] {
        var value: [String:Any]=["session_id":sessionID,"content":content,"due_at":dueAt,"request_id":requestID,"confirmed":true]
        if let repeatRule {value["repeat_rule"]=repeatRule}
        if let timeZone {value["time_zone"]=timeZone}
        if let quietStart {value["quiet_start"]=quietStart}
        if let quietEnd {value["quiet_end"]=quietEnd}
        if let allowContact {value["allow_contact"]=allowContact}
        if let contactWindowMinutes {value["contact_window_minutes"]=contactWindowMinutes}
        if let contactTopic {value["contact_topic"]=contactTopic}
        return value
    }
}
public struct EchoFollowupFormDraft: Codable, Equatable, Sendable {
    public var sessionID: String
    public var origin: String
    public var content: String = ""
    public var due: Date = Date().addingTimeInterval(3600)
    public var repeatRule: String = "once"
    public var timeZone: String = TimeZone.current.identifier
    public var usesQuietHours = false
    public var quietStart = "22:00"
    public var quietEnd = "08:00"
    public var allowContact = false
    public var contactWindowMinutes = 30
    public var contactTopic = ""
    public init(sessionID: String, origin: String) {self.sessionID=sessionID; self.origin=origin}
    public init(_ pending: EchoPendingFollowup) {
        sessionID=pending.sessionID; origin=pending.origin; content=pending.content; due=EchoFollowup.parse(pending.dueAt) ?? Date()
        repeatRule=pending.repeatRule ?? "once"; timeZone=pending.timeZone ?? "UTC"
        usesQuietHours=pending.quietStart != nil; quietStart=pending.quietStart ?? "22:00"; quietEnd=pending.quietEnd ?? "08:00"
        allowContact=pending.allowContact ?? false; contactWindowMinutes=pending.contactWindowMinutes ?? 30; contactTopic=pending.contactTopic ?? pending.content
    }
}
public struct EchoChatResult: Codable, Sendable {
    public let messages: [EchoMessage]
    public let memories: [EchoMemory]?
    public let reply: String?
    public let cancelled: Bool?
}
public struct EchoTurnRecord: Codable, Sendable {
    public let requestId: String
    public let sessionId: String
    public let status: String
    public let cancelRequested: Bool?
    public let errorCode: String?
    public let result: EchoChatResult?
    /// Only this exact durable server record proves that this specific turn never started.
    public func confirmsBusyNotAccepted(_ pending: EchoPendingTurn) -> Bool {
        requestId == pending.requestID && sessionId == pending.sessionID && status == "unknown" &&
        errorCode == "conversation_busy_not_accepted" && result == nil
    }
    /// A terminal uncertainty may be released locally only after an explicit review.
    /// This never means that server work was cancelled or should be sent again.
    public var permitsEndingLocalWait: Bool { status == "unknown" && result == nil }
    public var cancellationNotice: String {
        if result?.cancelled == true { return "已停止这次回复。你发过的话仍保留。" }
        if result != nil { return "这次回复已完成，未能撤回。请核对聊天记录；没有重新发送。" }
        return "已请求停止，结果仍未确认。请稍后核对；这不代表服务端已经停止。"
    }
}
public enum EchoChatSubmission: Sendable {
    case completed(EchoChatResult)
    case pending(EchoTurnRecord)
}
public struct EchoPendingTurn: Codable, Sendable {
    public let requestID: String
    public let sessionID: String
    public let text: String
    public let origin: String
    public var cancelWanted: Bool
    /// Optional for backward-compatible decoding of pending requests saved by v0.1.
    public var memoryProposals: Bool?
    public let timeZone: String?
    public init(sessionID: String, text: String, origin: String, requestID: String = UUID().uuidString, cancelWanted: Bool = false, memoryProposals: Bool = false, timeZone: String? = nil) {
        self.sessionID = sessionID; self.text = text; self.origin = origin
        self.requestID = requestID; self.cancelWanted = cancelWanted; self.memoryProposals = memoryProposals
        self.timeZone=timeZone
    }
}
public struct EchoSelectedFile: Codable, Identifiable, Sendable {
    public let name: String
    public let text: String
    public var id: String { name }
    public init(name: String, text: String) throws {
        let extensions = ["md", "markdown", "txt", "json", "py", "ts", "js", "csv"]
        guard !name.contains("/"), !name.contains("\\"), name.count <= 200,
              !name.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains),
              extensions.contains((name as NSString).pathExtension.lowercased()) else {
            throw EchoAPIError.message("请选择 .md、.txt、.json、代码或 CSV 文本文件。")
        }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !text.contains("\0") else {
            throw EchoAPIError.message("文件没有可读文本。")
        }
        self.name = name
        self.text = String(String.UnicodeScalarView(text.unicodeScalars.prefix(4_000)))
    }
}
