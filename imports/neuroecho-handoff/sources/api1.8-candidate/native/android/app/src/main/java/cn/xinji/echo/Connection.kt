package cn.xinji.echo

import java.net.URI
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

/** Identity is the personal service and its paired device, never merely an address. */
data class PairedProfile(val origin: String, val serviceInstanceId: String, val conversationId: String, val deviceId: String, val label: String, val expiresAt: String, val credentialGeneration: String) {
    val scope: String get() = connectionHash(listOf(origin, serviceInstanceId, conversationId, deviceId, credentialGeneration).joinToString("\u0000"))
    fun json() = json("origin" to origin, "service_instance_id" to serviceInstanceId, "conversation_id" to conversationId, "device_id" to deviceId, "label" to label, "expires_at" to expiresAt, "credential_generation" to credentialGeneration)
    fun expired(now: Instant = Instant.now()) = !Instant.parse(expiresAt).isAfter(now)
}
data class PairedCredential(val profile: PairedProfile, val token: String) {
    fun encode(): String = profile.json().put("token", token).toString()
}
fun connectionHash(value: String): String = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
object PairingPolicy {
    fun origin(input: String): String {
        val uri = URI(EndpointPolicy.validate(input, false))
        require(uri.port == -1 || uri.port in 1..65535) { "填写有效的 HTTPS 端口。" }
        val host = uri.host.lowercase().let { if (':' in it && !it.startsWith("[")) "[$it]" else it }
        return "https://" + host + if (uri.port == -1 || uri.port == 443) "" else ":${uri.port}"
    }
    fun validToken(value: String) = Regex("^echo_pair_[A-Za-z0-9_-]{43}$").matches(value)
    private fun identifier(value: String): Boolean = value.isNotBlank() && value.length <= 200 && value.none { it.isISOControl() }
    fun verify(origin: String, token: String, receipt: JSONObject, now: Instant = Instant.now(), generation: String = UUID.randomUUID().toString()): PairedCredential {
        require(validToken(token)) { "请填写电脑上为这部设备生成的配对令牌。" }
        require(receipt.opt("scope") == "personal_core" && receipt.opt("local_actions_allowed") == false) { "服务未提供所需的个人数据边界。" }
        val device = receipt.optJSONObject("device") ?: error("配对回执缺少设备身份。")
        val service = receipt.opt("service_instance_id") as? String ?: ""
        val sid = receipt.opt("conversation_id") as? String ?: ""
        val id = device.opt("id") as? String ?: ""
        val label = device.opt("label") as? String ?: ""
        val created = device.opt("created_at") as? String ?: ""
        val expires = device.opt("expires_at") as? String ?: ""
        require(listOf(service, sid, id).all(::identifier) && identifier(label) && label.length <= 80 && device.has("revoked_at") && device.isNull("revoked_at")) { "配对身份或撤销状态无效。" }
        require(runCatching { Instant.parse(expires).isAfter(now) && Instant.parse(expires).isAfter(Instant.parse(created)) }.getOrDefault(false)) { "设备令牌已过期，或有效期无法核对。" }
        return PairedCredential(PairedProfile(origin(origin), service, sid, id, label, expires, generation), token)
    }
    fun profile(value: String): PairedProfile {
        val obj = JSONObject(value)
        val result = PairedProfile(origin(obj.getString("origin")), obj.getString("service_instance_id"), obj.getString("conversation_id"), obj.getString("device_id"), obj.getString("label"), obj.getString("expires_at"), obj.getString("credential_generation"))
        require(listOf(result.serviceInstanceId, result.conversationId, result.deviceId, result.credentialGeneration).all(::identifier))
        Instant.parse(result.expiresAt)
        return result
    }
    fun decode(value: String): PairedCredential {
        val obj = JSONObject(value)
        val profile = profile(value)
        require(validToken(obj.getString("token")))
        return PairedCredential(profile, obj.getString("token"))
    }
    fun restore(verified: PairedCredential, previous: PairedProfile): PairedCredential {
        val actual = verified.profile
        require(actual.origin == previous.origin && actual.serviceInstanceId == previous.serviceInstanceId && actual.conversationId == previous.conversationId && actual.deviceId == previous.deviceId) { "验证的服务或设备身份与旧草稿不一致；原内容保留，没有迁移或重发。" }
        return verified.copy(profile = actual.copy(credentialGeneration = previous.credentialGeneration))
    }
    fun invalidates(error: ApiError) = error.status == 401 || (error.status == 409 && error.code == "service_instance_mismatch")
}

/** Storage-independent authenticated envelope. The Android adapter supplies a non-exportable key. */
interface VaultKeyProvider { fun key(create: Boolean): SecretKey }
class CredentialCipher(private val provider: VaultKeyProvider) {
    fun seal(name: String, plaintext: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, provider.key(true))
        cipher.updateAAD(name.toByteArray(Charsets.UTF_8))
        val encoder = Base64.getEncoder()
        return "v1:" + encoder.encodeToString(cipher.iv) + ":" + encoder.encodeToString(cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8)))
    }
    fun open(name: String, envelope: String): String {
        val parts = envelope.split(':'); require(parts.size == 3 && parts[0] == "v1") { "本机加密数据格式无法核对；没有清除。" }
        val decoder = Base64.getDecoder(); val iv = decoder.decode(parts[1]); require(iv.size == 12)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, provider.key(false), GCMParameterSpec(128, iv))
        cipher.updateAAD(name.toByteArray(Charsets.UTF_8))
        return String(cipher.doFinal(decoder.decode(parts[2])), Charsets.UTF_8)
    }
}

/** Generation guards apply before sending and before consuming every reply. */
class ConnectionEpoch {
    @Volatile var value: Long = 0; private set
    fun advance() { value++ }
    fun requireCurrent(captured: Long) { check(value == captured) { "连接身份已变化，旧请求没有用于当前页面。" } }
    fun accepts(captured: Long) = value == captured
}

/** All values here are encrypted envelopes. A failed atomic commit must retain the old map. */
interface VaultStorage {
    val names: Set<String>
    fun get(name: String): String?
    fun commit(changes: Map<String, String?>, blocked: Boolean? = null, endpoint: String? = null): Boolean
}
open class DeviceVault(private val storage: VaultStorage, provider: VaultKeyProvider) {
    private val cipher = CredentialCipher(object : VaultKeyProvider {
        override fun key(create: Boolean): SecretKey = provider.key(create && storage.names.none { it.startsWith("sealed:") })
    })
    fun read(name: String): String? = storage.get("sealed:$name")?.let { cipher.open(name, it) }
    fun write(name: String, value: String?): Boolean = storage.commit(mapOf("sealed:$name" to value?.let { cipher.seal(name, it) }))
    private fun quarantine(profile: PairedProfile): Pair<String, String> = "sealed:quarantine:" + profile.scope to cipher.seal("quarantine:" + profile.scope, profile.json().toString())
    fun activate(credential: PairedCredential, previous: PairedProfile? = null): Boolean {
        val changes = mutableMapOf<String, String?>("sealed:active-credential" to cipher.seal("active-credential", credential.encode()), "sealed:credential:" + credential.profile.scope to cipher.seal("credential:" + credential.profile.scope, credential.encode()), "sealed:locked-profile" to null)
        previous?.let { val (name, value) = quarantine(it); changes[name] = value }
        return storage.commit(changes, blocked = false)
    }
    fun useLocal(endpoint: String, previous: PairedProfile? = null): Boolean {
        val changes = mutableMapOf<String, String?>("sealed:active-credential" to null, "sealed:locked-profile" to null)
        previous?.let { val (name, value) = quarantine(it); changes[name] = value }
        return storage.commit(changes, blocked = false, endpoint = endpoint)
    }
    fun lock(profile: PairedProfile?, retireCredential: Boolean = true): Boolean {
        // A revoked/expired credential is removed even if the key is unavailable.
        // Instance mismatch only parks it; explicit recovery must verify the original identity.
        val changes = mutableMapOf<String,String?>("sealed:active-credential" to null)
        if (retireCredential && profile != null) changes["sealed:credential:" + profile.scope] = null
        val blocked = storage.commit(changes, blocked = true)
        if (profile == null) return blocked
        val (name, value) = quarantine(profile)
        val saved = storage.commit(mapOf("sealed:locked-profile" to cipher.seal("locked-profile", profile.json().toString()), name to value))
        return blocked && saved
    }
    fun savedCredential(profile: PairedProfile): PairedCredential? = read("credential:" + profile.scope)?.let(PairingPolicy::decode)?.also {
        require(it.profile.scope == profile.scope && it.profile.origin == profile.origin && it.profile.deviceId == profile.deviceId && it.profile.serviceInstanceId == profile.serviceInstanceId && it.profile.conversationId == profile.conversationId) { "本机凭据与旧身份不一致；未使用或迁移。" }
    }
    fun retireSavedCredential(profile: PairedProfile): Boolean = storage.commit(mapOf("sealed:credential:" + profile.scope to null))
    fun savedProfiles(): List<PairedProfile> = storage.names.filter { it.startsWith("sealed:quarantine:") }.sorted().map { name ->
        val aad = name.removePrefix("sealed:")
        PairingPolicy.profile(read(aad) ?: error("旧连接身份无法读取；未删除。"))
    }.distinctBy { it.scope }
    fun eraseSavedProfile(profile: PairedProfile): Boolean {
        val active = read("active-credential")?.let(PairingPolicy::decode)
        require(active?.profile?.scope != profile.scope) { "请先停止使用当前设备令牌，再移除此连接的本机资料。" }
        val locked = read("locked-profile")?.let(PairingPolicy::profile)
        val names = storage.names.filter { it == "sealed:quarantine:" + profile.scope || it == "sealed:credential:" + profile.scope || (it.startsWith("sealed:data:") && it.endsWith("-" + profile.scope)) }.toMutableList()
        if (locked?.scope == profile.scope) names += "sealed:locked-profile"
        return storage.commit(names.associateWith { null })
    }

}
