import Foundation

/// Ledger metadata deliberately carries neither diary date nor text.
public struct EchoMoodOperation: Decodable, Equatable, Sendable {
    public let sessionId: String
    public let requestId: String
    public let operationSha256: String?
    public let kind: String?
    public let state: String
    public let resultUpdatedAt: String?
    private enum CodingKeys: String, CodingKey, CaseIterable {case sessionId, requestId, operationSha256, kind, state, resultUpdatedAt}
    private struct AnyKey: CodingKey {
        let stringValue: String
        let intValue: Int? = nil
        init?(stringValue: String) {self.stringValue=stringValue}
        init?(intValue: Int) {return nil}
    }
    public init(from decoder: Decoder) throws {
        // Typed allKeys omits unknown keys. Inspect a dynamic container first;
        // keyDecodingStrategy applies the same conversion to both containers.
        let keys=try decoder.container(keyedBy:AnyKey.self)
        guard Set(keys.allKeys.map(\.stringValue)) == Set(CodingKeys.allCases.map(\.rawValue)) else {
            throw DecodingError.dataCorrupted(.init(codingPath:decoder.codingPath,debugDescription:"Ledger receipt must contain exactly six fields"))
        }
        let c=try decoder.container(keyedBy:CodingKeys.self)
        // decodeIfPresent alone would silently accept missing nullable keys.
        for key in [CodingKeys.sessionId,.requestId,.operationSha256,.kind,.state,.resultUpdatedAt] {
            guard c.contains(key) else {throw DecodingError.keyNotFound(key,.init(codingPath:decoder.codingPath,debugDescription:"Missing ledger field"))}
        }
        sessionId=try c.decode(String.self,forKey:.sessionId);requestId=try c.decode(String.self,forKey:.requestId)
        operationSha256=try c.decodeIfPresent(String.self,forKey:.operationSha256);kind=try c.decodeIfPresent(String.self,forKey:.kind)
        state=try c.decode(String.self,forKey:.state);resultUpdatedAt=try c.decodeIfPresent(String.self,forKey:.resultUpdatedAt)
    }
    public func matches(sessionID: String, mutation: EchoMoodMutation) -> Bool {
        guard mutation.validLedgerIdentity,sessionId == sessionID,requestId == mutation.requestID else {return false}
        if state == "not_found" {return operationSha256 == nil && kind == nil && resultUpdatedAt == nil}
        guard operationSha256 == mutation.operationHash, kind == mutation.kind.rawValue else {return false}
        switch state {
        case "applied":
            guard let token=resultUpdatedAt,EchoFollowup.parse(token) != nil else {return false}
            return mutation.kind == .save ? token != mutation.expectedUpdatedAt : token == mutation.expectedUpdatedAt
        case "conflict":return resultUpdatedAt == nil || EchoFollowup.parse(resultUpdatedAt) != nil
        case "cancelled":return resultUpdatedAt == nil
        default:return false
        }
    }
}
