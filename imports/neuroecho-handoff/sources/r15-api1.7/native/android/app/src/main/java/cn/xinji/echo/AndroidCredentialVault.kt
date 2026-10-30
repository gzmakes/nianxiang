package cn.xinji.echo

import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** No KeyChain, exported key, plaintext fallback, biometric prompt or account flow. */
class AndroidVaultKeyProvider : VaultKeyProvider {
    override fun key(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val alias = "cn.xinji.echo.device.v1"
        if (store.containsAlias(alias)) return store.getKey(alias, null) as SecretKey
        check(create) { "本机密钥不可用；原加密草稿仍保留，请勿清除应用数据。" }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setRandomizedEncryptionRequired(true).build())
            generateKey()
        }
    }
}
private class AndroidVaultStorage(private val preferences: SharedPreferences) : VaultStorage {
    override val names get() = preferences.all.keys
    override fun get(name: String): String? = preferences.getString(name, null)
    override fun commit(changes: Map<String, String?>, blocked: Boolean?, endpoint: String?): Boolean {
        val editor = preferences.edit()
        changes.forEach { (name, value) -> if (value == null) editor.remove(name) else editor.putString(name, value) }
        blocked?.let { editor.putBoolean("paired-blocked", it) }
        endpoint?.let { editor.putString("endpoint", it) }
        return editor.commit()
    }
}
class AndroidCredentialVault(preferences: SharedPreferences) : DeviceVault(AndroidVaultStorage(preferences), AndroidVaultKeyProvider())
