import Foundation
import Security

@MainActor protocol EchoDeviceCredentialStore: AnyObject {
    func save(_ token: String,for profile: EchoDeviceProfile) throws
    func read(for profile: EchoDeviceProfile) throws -> String
    func remove(for profile: EchoDeviceProfile) throws
}
enum EchoCredentialStoreError: LocalizedError {
    case locked,missing,unavailable
    var errorDescription: String? {switch self {case .locked:return "设备凭据暂时锁定，请解锁后手动重试；没有删除连接。";case .missing:return "这台设备没有保存的连接令牌，请在电脑端重新生成。";case .unavailable:return "未能安全保存或清理设备凭据；没有发送新写入，请稍后重试。"}}
}
/// No query occurs in init. Only explicit Connect / Restore / Forget UI actions,
/// or a definitive current-device authentication rejection, invoke these methods.
@MainActor final class EchoKeychainDeviceCredentialStore: EchoDeviceCredentialStore {
    private func query(_ profile: EchoDeviceProfile) -> [String:Any] {
        [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:"cn.xinji.echo.device-connection.v1",kSecAttrAccount as String:profile.vaultAccount,kSecAttrSynchronizable as String:false,kSecUseDataProtectionKeychain as String:true]
    }
    private func checked(_ status: OSStatus) throws {
        guard status != errSecSuccess else {return}
        if status == errSecInteractionNotAllowed || status == errSecAuthFailed {throw EchoCredentialStoreError.locked}
        if status == errSecItemNotFound {throw EchoCredentialStoreError.missing}
        throw EchoCredentialStoreError.unavailable
    }
    func save(_ token: String,for profile: EchoDeviceProfile) throws {
        guard EchoDeviceAuthorization.validToken(token) else {throw EchoCredentialStoreError.unavailable}
        let attributes:[String:Any] = [kSecValueData as String:Data(token.utf8),kSecAttrAccessible as String:kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let status=SecItemUpdate(query(profile) as CFDictionary,attributes as CFDictionary)
        if status == errSecItemNotFound {var item=query(profile);attributes.forEach {item[$0.key]=$0.value};try checked(SecItemAdd(item as CFDictionary,nil))}
        else {try checked(status)}
    }
    func read(for profile: EchoDeviceProfile) throws -> String {
        var item=query(profile);item[kSecReturnData as String]=true;item[kSecMatchLimit as String]=kSecMatchLimitOne
        var found: CFTypeRef?;try checked(SecItemCopyMatching(item as CFDictionary,&found))
        guard let data=found as? Data,let token=String(data:data,encoding:.utf8),EchoDeviceAuthorization.validToken(token) else {throw EchoCredentialStoreError.unavailable}
        return token
    }
    func remove(for profile: EchoDeviceProfile) throws {let status=SecItemDelete(query(profile) as CFDictionary);if status != errSecItemNotFound {try checked(status)}}
}
