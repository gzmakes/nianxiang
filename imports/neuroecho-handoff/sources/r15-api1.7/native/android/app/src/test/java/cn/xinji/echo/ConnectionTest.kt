package cn.xinji.echo

import org.junit.Test
import org.junit.Assert.*
import java.time.Instant
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import org.json.JSONObject

class ConnectionTest {
    private val token = "echo_pair_" + "A".repeat(43)
    private val now = Instant.parse("2026-10-30T00:00:00Z")
    private fun receipt() = json("service_instance_id" to "instance-a", "conversation_id" to "canonical", "scope" to "personal_core", "local_actions_allowed" to false,
        "device" to json("id" to "device-a", "label" to "合成手机", "created_at" to "2026-10-29T00:00:00Z", "expires_at" to "2026-11-30T00:00:00Z", "revoked_at" to JSONObject.NULL))
    private fun profile() = PairingPolicy.verify("https://EXAMPLE.com:443/", token, receipt(), now, "generation-a")
    private fun rejects(block: () -> Unit) { var failed = false; try { block() } catch (_: Exception) { failed = true }; assertTrue("must reject", failed) }
    @Test fun canonicalHttpsOriginRemovesOnlyDefaultPortAndCase() { assertEquals("https://example.com", PairingPolicy.origin("https://EXAMPLE.com:443/")); assertEquals("https://example.com:8443", PairingPolicy.origin("https://example.com:8443")) }
    @Test fun remoteOriginRejectsHttpEmbeddedCredentialsPathsQueriesAndInvalidPorts() { listOf("http://127.0.0.1", "https://user@example.com", "https://example.com/path", "https://example.com?token=bad", "https://example.com#bad", "https://example.com:0", "https://example.com:99999").forEach { rejects { PairingPolicy.origin(it) } } }
    @Test fun onlyExactDeviceTokenIsAcceptedAndNeverAnAddressCredential() { assertTrue(PairingPolicy.validToken(token)); listOf("", token+"A", token.dropLast(1), token+"\n", "sk-"+"A".repeat(43), token.replace('A',' ')).forEach { assertFalse(PairingPolicy.validToken(it)) } }
    @Test fun completePairingBindsServiceCanonicalConversationDeviceAndExactExpiry() { val p=profile().profile; assertEquals("instance-a",p.serviceInstanceId); assertEquals("canonical",p.conversationId); assertEquals("device-a",p.deviceId); assertEquals("2026-11-30T00:00:00Z",p.expiresAt); assertFalse(p.expired(now)) }
    @Test fun revokedMissingOrWrongTypedBoundaryDoesNotActivate() { for (r in listOf(receipt().put("local_actions_allowed", "false"), receipt().put("scope","all"), receipt().also { it.getJSONObject("device").remove("revoked_at") }, receipt().also { it.getJSONObject("device").put("revoked_at", "2026-10-30T00:00:00Z") }, receipt().put("conversation_id", 3))) rejects { PairingPolicy.verify("https://example.com",token,r,now) } }
    @Test fun expiryIsRequiredValidAndFuture() { for(value in listOf("", "tomorrow", "2026-10-30T00:00:00Z", "2026-10-29T00:00:00Z")) rejects { PairingPolicy.verify("https://example.com",token,receipt().also { it.getJSONObject("device").put("expires_at",value) },now) } }
    @Test fun encryptedCredentialRoundTripPreservesGenerationAndToken() { val value=profile(); assertEquals(value,PairingPolicy.decode(value.encode())); assertEquals(value.profile,PairingPolicy.profile(value.profile.json().toString())) }
    @Test fun eachIdentityAndCredentialGenerationGetsDistinctNamespace() { val p=profile().profile; val scopes=listOf(p,p.copy(origin="https://other.example.com"),p.copy(serviceInstanceId="instance-b"),p.copy(conversationId="other"),p.copy(deviceId="device-b"),p.copy(credentialGeneration="generation-b")).map{it.scope}; assertEquals(6,scopes.toSet().size); assertFalse(scopes.contains(connectionHash(p.origin).take(24))) }
    @Test fun only401AndExactServiceMismatchInvalidateNot403OrOther409() { assertTrue(PairingPolicy.invalidates(ApiError(401,""))); assertTrue(PairingPolicy.invalidates(ApiError(409,"","service_instance_mismatch"))); for(status in listOf(400,403,408,409,428,429,500)) assertFalse(PairingPolicy.invalidates(ApiError(status,"","paired_operation_forbidden"))) }
    @Test fun epochRejectsAllOldRepliesAndRequiresNoAutomaticRetry() { val e=ConnectionEpoch(); val first=e.value;e.requireCurrent(first); e.advance(); rejects { e.requireCurrent(first) }; val second=e.value;e.advance(); assertFalse(e.accepts(second)); assertTrue(e.accepts(e.value)) }
    private class Keys : VaultKeyProvider { var existing:SecretKey?=null; var creations=0; override fun key(create:Boolean):SecretKey { if(existing==null && create){existing=KeyGenerator.getInstance("AES").apply{init(256)}.generateKey();creations++}; return existing ?: error("key unavailable") } }
    @Test fun authenticatedEnvelopeKeepsUnicodeAndNeverContainsTokenOrDraft() { val keys=Keys();val cipher=CredentialCipher(keys); val raw=token+" 私人合成草稿😀";val sealed=cipher.seal("scope-a",raw); assertFalse(sealed.contains(token));assertFalse(sealed.contains("合成"));assertEquals(raw,cipher.open("scope-a",sealed));assertEquals(1,keys.creations) }
    @Test fun eachEncryptionUsesNewIv() { val cipher=CredentialCipher(Keys()); val a=cipher.seal("same","same"); val b=cipher.seal("same","same"); assertNotEquals(a,b);assertEquals(cipher.open("same",a),cipher.open("same",b)) }
    @Test fun cipherRejectsCrossDeviceNamespaceAndTampering() { val cipher=CredentialCipher(Keys());val sealed=cipher.seal("scope-a", "合成未知请求");rejects { cipher.open("scope-b",sealed) };val split=sealed.split(':');val bytes=java.util.Base64.getDecoder().decode(split[2]);bytes[0]=(bytes[0].toInt() xor 1).toByte();rejects { cipher.open("scope-a",split.take(2).joinToString(":")+":"+java.util.Base64.getEncoder().encodeToString(bytes)) } }
    @Test fun missingOrWrongKeyDoesNotGenerateReplacementOrReturnPlaintext() { val keys=Keys();val cipher=CredentialCipher(keys);val envelope=cipher.seal("scope","合成unknown");keys.existing=null;rejects { cipher.open("scope",envelope) };assertEquals(1,keys.creations);val other=CredentialCipher(Keys());other.seal("x","x");rejects { other.open("scope",envelope) };assertTrue(envelope.startsWith("v1:")) }
    @Test fun malformedEnvelopeDoesNotFallbackToPlaintext() { val cipher=CredentialCipher(Keys());listOf("合成明文", "v2:a:b", "v1:AA==:AA==", "").forEach { rejects { cipher.open("scope",it) } } }
    @Test fun pairedTransportCannotBeConstructedForCleartextOrNonCanonicalOrigin() { rejects { EchoApi("http://127.0.0.1",DeviceAuthorization(token)) };rejects { EchoApi("https://EXAMPLE.com:443",DeviceAuthorization(token)) }; EchoApi("https://example.com",DeviceAuthorization(token,"instance-a")) }

    private class MemoryStore : VaultStorage {
        val values = mutableMapOf<String,String>(); var fail = false; var blocked = false; var endpoint: String? = null
        override val names get() = values.keys.toSet()
        override fun get(name:String) = values[name]
        override fun commit(changes:Map<String,String?>,blocked:Boolean?,endpoint:String?):Boolean {
            if(fail)return false
            changes.forEach { (key,value) -> if(value==null)values.remove(key) else values[key]=value }
            blocked?.let{this.blocked=it};endpoint?.let{this.endpoint=it};return true
        }
    }
    @Test fun failedActivationRetainsOldCredentialAndCiphertextExactly() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val old=profile();assertTrue(vault.activate(old));val before=store.values.toMap();store.fail=true
        assertFalse(vault.activate(old.copy(profile=old.profile.copy(deviceId="device-b",credentialGeneration="next")),old.profile));assertEquals(before,store.values);assertEquals(old,PairingPolicy.decode(vault.read("active-credential")!!))
    }
    @Test fun credentialAndAllDraftKindsAreStoredOnlyAsAuthenticatedEnvelopes() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val current=profile();vault.activate(current)
        for(kind in listOf("draft", "pending", "memory-draft", "followup-draft", "mood-draft", "topics"))assertTrue(vault.write("data:$kind-${current.profile.scope}","私人合成-$kind"))
        assertTrue(store.values.values.all{it.startsWith("v1:")});assertTrue(store.values.values.none{it.contains(token)||it.contains("私人")});assertEquals("私人合成-pending",vault.read("data:pending-${current.profile.scope}"))
    }
    @Test fun lockErasesOnlyCredentialAndPreservesUnknownPayloadAndIdentityDescriptor() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val current=profile();vault.activate(current);vault.write("data:pending-${current.profile.scope}","原始请求-id-body")
        val pending=store.values["sealed:data:pending-${current.profile.scope}"]
        assertTrue(vault.lock(current.profile));assertTrue(store.blocked);assertNull(vault.read("active-credential"));assertEquals(pending,store.values["sealed:data:pending-${current.profile.scope}"])
        assertEquals(current.profile,PairingPolicy.profile(vault.read("quarantine:${current.profile.scope}")!!));assertEquals(current.profile,PairingPolicy.profile(vault.read("locked-profile")!!))
    }
    @Test fun newGenerationDoesNotReadOrCopyOldPending() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val old=profile();vault.activate(old);vault.write("data:pending-${old.profile.scope}","same-id-exact-body");val next=old.copy(profile=old.profile.copy(credentialGeneration="next"))
        assertTrue(vault.activate(next,old.profile));assertNull(vault.read("data:pending-${next.profile.scope}"));assertEquals("same-id-exact-body",vault.read("data:pending-${old.profile.scope}"));assertNotNull(vault.read("quarantine:${old.profile.scope}"))
    }
    @Test fun lostKeyDoesNotOverwriteAnyEnvelopeOrGenerateReplacement() {
        val store=MemoryStore();val keys=Keys();val vault=DeviceVault(store,keys);val old=profile();vault.activate(old);val before=store.values.toMap();keys.existing=null
        rejects { vault.activate(old.copy(profile=old.profile.copy(credentialGeneration="next")),old.profile) };assertEquals(before,store.values);assertEquals(1,keys.creations)
    }
    @Test fun lockStillBlocksAndRemovesTokenWhenKeyIsUnavailable() {
        val store=MemoryStore();val keys=Keys();val vault=DeviceVault(store,keys);val old=profile();vault.activate(old);vault.write("data:pending-${old.profile.scope}","合成unknown");keys.existing=null
        rejects { vault.lock(old.profile) };assertTrue(store.blocked);assertFalse(store.values.containsKey("sealed:active-credential"));assertTrue(store.values.containsKey("sealed:data:pending-${old.profile.scope}"));assertEquals(1,keys.creations)
    }
    @Test fun explicitLocalModeRetainsQuarantineAndDoesNotMigrateDrafts() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val old=profile();vault.activate(old);vault.write("data:pending-${old.profile.scope}","合成unknown");assertTrue(vault.useLocal(EndpointPolicy.DEFAULT,old.profile))
        assertEquals(EndpointPolicy.DEFAULT,store.endpoint);assertFalse(store.blocked);assertNull(vault.read("active-credential"));assertNotNull(vault.read("quarantine:${old.profile.scope}"));assertEquals("合成unknown",vault.read("data:pending-${old.profile.scope}"))
    }

    @Test fun explicitRestoreOnlyReusesOldGenerationAfterExactOnlineIdentityMatch() {
        val old=profile();val verified=PairingPolicy.verify(old.profile.origin,token,receipt(),now,"new-generation")
        val restored=PairingPolicy.restore(verified,old.profile);assertEquals(old.profile.scope,restored.profile.scope);assertEquals("generation-a",restored.profile.credentialGeneration)
    }
    @Test fun restoreRejectsAnyDifferentOriginServiceConversationOrDevice() {
        val old=profile();for(p in listOf(old.profile.copy(origin="https://other.example.com"),old.profile.copy(serviceInstanceId="instance-b"),old.profile.copy(conversationId="different"),old.profile.copy(deviceId="device-b"))) rejects { PairingPolicy.restore(old.copy(profile=p),old.profile) }
    }
    @Test fun savedIdentityRestoresExactUnknownBodyWithoutCreatingOrReplayingRequest() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val old=profile();vault.activate(old);val body="{\"request_id\":\"frozen-id\",\"text\":\"合成原话\"}";vault.write("data:pending-${old.profile.scope}",body);vault.lock(old.profile)
        val previous=vault.savedProfiles().single();val restored=PairingPolicy.restore(PairingPolicy.verify(old.profile.origin,token,receipt(),now,"new-generation"),previous);vault.activate(restored)
        assertEquals(body,vault.read("data:pending-${restored.profile.scope}"));assertEquals(old.profile.scope,restored.profile.scope)
    }
    @Test fun explicitArchiveRemovalDeletesOnlyThatScopesDraftsAndDescriptor() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val a=profile();val b=a.copy(profile=a.profile.copy(deviceId="device-b",credentialGeneration="b"));vault.activate(a);vault.write("data:pending-${a.profile.scope}","a-unknown");vault.activate(b,a.profile);vault.write("data:pending-${b.profile.scope}","b-unknown")
        assertTrue(vault.eraseSavedProfile(a.profile));assertNull(vault.read("data:pending-${a.profile.scope}"));assertNull(vault.read("quarantine:${a.profile.scope}"));assertEquals("b-unknown",vault.read("data:pending-${b.profile.scope}"));assertEquals(b,PairingPolicy.decode(vault.read("active-credential")!!))
    }
    @Test fun activeIdentityCannotBeErasedBeforeExplicitDisconnect() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val a=profile();vault.activate(a);vault.write("data:pending-${a.profile.scope}","a-unknown");val before=store.values.toMap();rejects { vault.eraseSavedProfile(a.profile) };assertEquals(before,store.values)
    }
    @Test fun removalFailurePreservesCiphertextsAndBlockedMarker() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val a=profile();vault.activate(a);vault.write("data:pending-${a.profile.scope}","a-unknown");vault.lock(a.profile);val before=store.values.toMap();store.fail=true;assertFalse(vault.eraseSavedProfile(a.profile));assertEquals(before,store.values);assertTrue(store.blocked)
    }

    @Test fun switchingRetainsEncryptedOriginalCredentialForExplicitRestoreOnly() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val a=profile();val b=a.copy(profile=a.profile.copy(deviceId="device-b",credentialGeneration="b"));vault.activate(a);vault.activate(b,a.profile)
        assertEquals(a,vault.savedCredential(a.profile));assertEquals(b,PairingPolicy.decode(vault.read("active-credential")!!));assertFalse(store.values.values.any{it.contains(token)})
    }
    @Test fun instanceMismatchParksTokenWhile401RetiresOnlyExactGeneration() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val a=profile();val b=a.copy(profile=a.profile.copy(deviceId="device-b",credentialGeneration="b"));vault.activate(a);vault.activate(b,a.profile);vault.lock(b.profile,retireCredential=false)
        assertEquals(b,vault.savedCredential(b.profile));assertEquals(a,vault.savedCredential(a.profile));assertNull(vault.read("active-credential"));vault.lock(b.profile,retireCredential=true)
        assertNull(vault.savedCredential(b.profile));assertEquals(a,vault.savedCredential(a.profile))
    }
    @Test fun retiringRejectedRecoveryDoesNotEraseCurrentConnection() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val a=profile();val b=a.copy(profile=a.profile.copy(deviceId="device-b",credentialGeneration="b"));vault.activate(a);vault.activate(b,a.profile);assertTrue(vault.retireSavedCredential(a.profile))
        assertNull(vault.savedCredential(a.profile));assertEquals(b,PairingPolicy.decode(vault.read("active-credential")!!));assertFalse(store.blocked)
    }
    @Test fun explicitArchiveRemovalAlsoRemovesOnlyItsEncryptedToken() {
        val store=MemoryStore();val vault=DeviceVault(store,Keys());val a=profile();val b=a.copy(profile=a.profile.copy(deviceId="device-b",credentialGeneration="b"));vault.activate(a);vault.activate(b,a.profile);vault.eraseSavedProfile(a.profile)
        assertNull(vault.savedCredential(a.profile));assertEquals(b,vault.savedCredential(b.profile));assertEquals(b,PairingPolicy.decode(vault.read("active-credential")!!))
    }
    @Test fun transportRejectsHeaderControlCharactersBeforeNetwork() { rejects { EchoApi("https://example.com",DeviceAuthorization(token,"instance\r\nOther: bad")) } }
}
