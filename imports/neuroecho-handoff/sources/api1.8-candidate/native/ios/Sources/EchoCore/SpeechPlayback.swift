import Foundation

/// Only already-rendered reply parts become speech input. Raw text is retained
/// solely to invalidate playback if the service edits the underlying message.
public struct EchoSpeechTarget: Equatable, Sendable {
    public let origin: String
    public let sessionID: String
    public let messageID: String
    public let rawText: String
    public let visibleParts: [String]
    public let deliveryPending: Bool?
    public let speechText: String
    public static func visibleReply(_ message: EchoMessage, origin: String, sessionID: String?, foreground: Bool) -> Self? {
        guard foreground,!origin.isEmpty,let sessionID,!sessionID.isEmpty,!message.id.isEmpty,
              message.role == "assistant",message.deliveryPending != true else {return nil}
        let parts=message.displayParts,body=spokenText(parts.joined(separator:"\n\n"))
        guard !body.isEmpty else {return nil}
        return Self(origin:origin,sessionID:sessionID,messageID:message.id,rawText:message.text,visibleParts:parts,deliveryPending:message.deliveryPending,speechText:body)
    }
    public static func spokenText(_ value: String) -> String {
        value.replacingOccurrences(of:#"\[表情[:：]\s*[^\]\r\n]+\]"#,with:"",options:.regularExpression)
            .replacingOccurrences(of:#"\[([^\]]+)\]\(https?://[^)]+\)"#,with:"$1",options:.regularExpression)
            .replacingOccurrences(of:#"[*_`#]"#,with:"",options:.regularExpression)
            .trimmingCharacters(in:.whitespacesAndNewlines)
    }
}
public struct EchoSpeechRequest: Equatable, Sendable {
    public enum Phase: Equatable, Sendable {case preparing,speaking}
    public let token: UUID
    public let target: EchoSpeechTarget
    public var phase: Phase
}
public enum EchoSpeechEvent: Equatable, Sendable {
    case started(UUID),finished(UUID),cancelled(UUID),failed(UUID)
    public var token: UUID {switch self {case .started(let t),.finished(let t),.cancelled(let t),.failed(let t):return t}}
}
/// No timers, devices, network or persistence. Begin is called only by a user tap;
/// reconciliation can stop an existing request but can never create speech.
public struct EchoSpeechState: Equatable, Sendable {
    public private(set) var active: EchoSpeechRequest?
    public init() {}
    @discardableResult public mutating func begin(_ target: EchoSpeechTarget) -> EchoSpeechRequest {
        let value=EchoSpeechRequest(token:UUID(),target:target,phase:.preparing);active=value;return value
    }
    @discardableResult public mutating func invalidate() -> UUID? {let token=active?.token;active=nil;return token}
    @discardableResult public mutating func receive(_ event: EchoSpeechEvent) -> Bool {
        guard var value=active,value.token == event.token else {return false}
        switch event {
        case .started:value.phase = .speaking;active=value
        case .finished,.cancelled,.failed:active=nil
        }
        return true
    }
    @discardableResult public mutating func reconcile(messages: [EchoMessage],origin: String,sessionID: String?,foreground: Bool) -> Bool {
        guard let active else {return false}
        let target=messages.first {$0.id == active.target.messageID}.flatMap {EchoSpeechTarget.visibleReply($0,origin:origin,sessionID:sessionID,foreground:foreground)}
        guard target != active.target else {return false}
        invalidate();return true
    }
}
