import Foundation

public struct EchoPairedDevice: Decodable, Equatable, Sendable {
    public struct Device: Decodable, Equatable, Sendable {
        public let id: String
        public let label: String
        public let createdAt: String
        public let expiresAt: String
        public let revokedAt: String?
        private enum CodingKeys: String,CodingKey {case id,label,createdAt,expiresAt,revokedAt}
        public init(from decoder: Decoder) throws {
            let c=try decoder.container(keyedBy:CodingKeys.self)
            guard c.contains(.revokedAt) else {throw DecodingError.keyNotFound(CodingKeys.revokedAt,.init(codingPath:decoder.codingPath,debugDescription:"Missing revocation field"))}
            id=try c.decode(String.self,forKey:.id);label=try c.decode(String.self,forKey:.label);createdAt=try c.decode(String.self,forKey:.createdAt);expiresAt=try c.decode(String.self,forKey:.expiresAt);revokedAt=try c.decodeIfPresent(String.self,forKey:.revokedAt)
        }
    }
    public let serviceInstanceId: String
    public let conversationId: String
    public let scope: String
    public let localActionsAllowed: Bool
    public let device: Device
    public var isValid: Bool {
        guard !serviceInstanceId.isEmpty,serviceInstanceId.count <= 128,
              !conversationId.isEmpty,conversationId.count <= 128,
              !device.id.isEmpty,device.id.count <= 128,
              !device.label.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty,device.label.count <= 80,
              scope == "personal_core",!localActionsAllowed,device.revokedAt == nil,
              [device.createdAt,device.expiresAt].allSatisfy({$0.hasSuffix("Z") || $0.hasSuffix("+00:00")}),
              let created=EchoFollowup.parse(device.createdAt),let expiry=EchoFollowup.parse(device.expiresAt) else {return false}
        return expiry > created && expiry > Date()

    }
}
/// Non-secret local connection metadata. Credential generation never comes from
/// a server response and is never silently assigned to a legacy pending request.
public struct EchoDeviceProfile: Codable, Equatable, Sendable {
    public let origin: String
    public let serviceInstanceID: String
    public let conversationID: String
    public let deviceID: String
    public let label: String
    public let expiresAt: String
    public let credentialGeneration: UUID
    public init(origin: String, receipt: EchoPairedDevice, credentialGeneration: UUID = UUID()) {
        self.origin=origin;serviceInstanceID=receipt.serviceInstanceId;conversationID=receipt.conversationId;deviceID=receipt.device.id;label=receipt.device.label;expiresAt=receipt.device.expiresAt;self.credentialGeneration=credentialGeneration
    }
    public var namespace: String {[origin,serviceInstanceID,deviceID,credentialGeneration.uuidString].joined(separator:"|paired|")}
    public var vaultAccount: String {Data(namespace.utf8).base64EncodedString()}
    public func matches(_ receipt: EchoPairedDevice) -> Bool {receipt.isValid && receipt.serviceInstanceId == serviceInstanceID && receipt.conversationId == conversationID && receipt.device.id == deviceID}
}
public struct EchoAuthenticationFailure: Sendable {
    public let profile: EchoDeviceProfile
    public let code: String
}
/// The bearer is memory-only here; it is intentionally neither Codable nor part
/// of a request snapshot. A rejected identity cannot issue another API request.
public final class EchoDeviceAuthorization: @unchecked Sendable {
    private let lock=NSLock()
    private var usable=true
    private var bearer: String
    public let profile: EchoDeviceProfile?
    public init(token: String, profile: EchoDeviceProfile? = nil) throws {
        guard Self.validToken(token) else {throw EchoAPIError.message("请粘贴电脑端显示的完整设备令牌；不是模型密钥。")}
        bearer=token;self.profile=profile
    }
    public static func validToken(_ value: String) -> Bool {value.utf8.count == 53 && value.range(of:#"^echo_pair_[A-Za-z0-9_-]{43}$"#,options:.regularExpression) != nil}
    public func header() throws -> String {lock.lock();defer {lock.unlock()};guard usable else {throw EchoAPIError.message("设备连接已失效，请重新连接；没有匿名重试。")};return "Bearer "+bearer}
    public func invalidate() {lock.lock();usable=false;bearer="";lock.unlock()}
}
