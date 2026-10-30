import Foundation

/// Metadata only. A cursor is opaque, memory-only and never a write receipt.
public struct EchoConversationChanges: Decodable,Equatable,Sendable {
    public let serviceInstanceId: String
    public let conversationId: String
    public let cursor: String
    public let resetRequired: Bool
    public let domains: [String]
    public let resetReason: String?
    private enum CodingKeys: String,CodingKey {case serviceInstanceId,conversationId,cursor,resetRequired,domains,resetReason}
    public init(from decoder: Decoder) throws {
        let c=try decoder.container(keyedBy:CodingKeys.self)
        guard c.contains(.resetReason) else {throw DecodingError.keyNotFound(CodingKeys.resetReason,.init(codingPath:decoder.codingPath,debugDescription:"Missing reset reason"))}
        serviceInstanceId=try c.decode(String.self,forKey:.serviceInstanceId);conversationId=try c.decode(String.self,forKey:.conversationId)
        cursor=try c.decode(String.self,forKey:.cursor);resetRequired=try c.decode(Bool.self,forKey:.resetRequired);domains=try c.decode([String].self,forKey:.domains);resetReason=try c.decodeIfPresent(String.self,forKey:.resetReason)
    }
    public static let knownDomains: Set<String> = ["conversation","messages","memories","sources","moods","followups","boundary","actions","turns"]
    public var isValid: Bool {
        !serviceInstanceId.isEmpty && serviceInstanceId.count <= 128 && !conversationId.isEmpty && conversationId.count <= 128 && Self.validCursor(cursor) && domains.count <= 64 && Set(domains).count == domains.count && domains.allSatisfy {!$0.isEmpty && $0.utf8.count <= 64 && $0.range(of:#"^[a-z_]+$"#,options:.regularExpression) != nil} && (resetRequired ? Self.knownDomains.isSubset(of:Set(domains)) && ["initial","identity_changed","too_old","ahead"].contains(resetReason ?? "") : resetReason == nil)
    }
    public static func validCursor(_ text: String) -> Bool {!text.isEmpty && text.utf8.count <= 2048 && text.range(of:#"^[A-Za-z0-9_-]+$"#,options:.regularExpression) != nil}

}
public enum EchoChangeSyncStatus: String,Sendable {case idle,checking,pending,updated,offline,unsupported}
public struct EchoChangeReadTicket: Equatable,Sendable {
    public let id: UUID
    public let scope: String
    public let epoch: UUID
    public let after: String?
}
/// Single-flight/read barrier bookkeeping independent of UI, timers and storage.
/// Cancellation invalidates a result but keeps the flight occupied until unwound.
public struct EchoChangePollState: Sendable {
    public private(set) var cursor: String?
    public private(set) var scope=""
    public private(set) var epoch=UUID()
    public private(set) var inFlight: UUID?
    public private(set) var failures=0
    public private(set) var pending=false
    public init() {}
    public var delaySeconds: Double {min(60,15 * pow(2,Double(min(2,failures))))}
    public mutating func bind(_ scope: String) {
        guard self.scope != scope else {return}
        self.scope=scope;epoch=UUID();cursor=nil;failures=0;pending=false
    }
    public mutating func interrupt() {epoch=UUID()}
    public mutating func begin(scope: String) -> EchoChangeReadTicket? {
        bind(scope);guard inFlight == nil else {return nil}
        let id=UUID();inFlight=id;return .init(id:id,scope:scope,epoch:epoch,after:cursor)
    }
    public func accepts(_ ticket: EchoChangeReadTicket) -> Bool {inFlight == ticket.id && scope == ticket.scope && epoch == ticket.epoch}
    public mutating func discovered(_ ticket: EchoChangeReadTicket) {if accepts(ticket) {pending=true}}
    public mutating func commit(_ ticket: EchoChangeReadTicket,cursor: String) -> Bool {
        guard accepts(ticket),EchoConversationChanges.validCursor(cursor) else {return false}
        self.cursor=cursor;pending=false;failures=0;return true
    }
    public mutating func failed(_ ticket: EchoChangeReadTicket) {if accepts(ticket) {failures=min(2,failures+1)}}
    public mutating func finish(_ ticket: EchoChangeReadTicket) {if inFlight == ticket.id {inFlight=nil}}
}
