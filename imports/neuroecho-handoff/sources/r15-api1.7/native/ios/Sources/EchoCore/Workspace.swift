import Foundation

public struct EchoSearchHit: Identifiable, Sendable {
    public enum Kind: String, Sendable { case message, memory }
    public let recordID: String
    public let kind: Kind
    public let text: String
    public let label: String
    public var id: String { kind.rawValue + ":" + recordID }
}
public enum EchoWorkspace {
    /// Matches the Web scope: only the already-loaded conversation and memories.
    public static func search(_ conversation: EchoConversation?, query: String) -> [EchoSearchHit] {
        let query = query.trimmingCharacters(in:.whitespacesAndNewlines)
        guard let conversation, !query.isEmpty else { return [] }
        let messages = conversation.messages.filter { $0.text.localizedCaseInsensitiveContains(query) }.map {
            EchoSearchHit(recordID:$0.id,kind:.message,text:$0.text,label:$0.role == "user" ? "你说过" : "回响")
        }
        let memories = conversation.memories.filter { $0.status != "deleted" && $0.text.localizedCaseInsensitiveContains(query) }.map {
            EchoSearchHit(recordID:$0.id,kind:.memory,text:$0.text,label:$0.status == "confirmed" ? "已确认记忆" : "待确认记忆")
        }
        return Array((messages + memories).prefix(100))
    }
    public static func normalizedTopic(_ label: String) -> String? {
        let label = label.trimmingCharacters(in:.whitespacesAndNewlines)
        return !label.isEmpty && label != "全部" && label.count <= 20 ? label : nil
    }
    public static func topic(for messageID: String, assignments: [String:String]) -> String { assignments[messageID] ?? "日常" }
    public static func topicLabels(assignments: [String:String]) -> [String] {
        ["全部", "日常"] + Set(assignments.values.filter { $0 != "日常" }).sorted()
    }
}
