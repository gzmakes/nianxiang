package cn.xinji.echo

import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.async
import kotlinx.coroutines.Dispatchers
import java.time.Instant

/** Synthetic HTTPS fixture only. Uses standard JDK certificate/hostname verification. */
fun main(args: Array<String>) = runBlocking {
    val origin = args[0]; val wrongHostname = args[1]
    val token = "echo_pair_" + "A".repeat(43)
    var count = 0
    fun verify(label: String, condition: Boolean) { check(condition) { label }; println("PASS $label"); count++ }
    suspend fun fails(label: String, block: suspend () -> Unit): Exception { try { block() } catch (error: Exception) { count++;println("PASS $label");return error };error("Expected failure: $label") }
    val verifier = EchoApi(origin, DeviceAuthorization(token))
    val receipt = verifier.get("/api/paired-device")
    val credential = PairingPolicy.verify(origin, token, receipt, Instant.parse("2026-10-30T00:00:00Z"), "test-generation")
    verify("real HTTPS paired receipt matches canonical identity", credential.profile.deviceId == "device-a" && credential.profile.serviceInstanceId == "instance-a")
    var invalid = 0
    val api = EchoApi(origin, DeviceAuthorization(token,"instance-a"), onInvalidCredential = { invalid++ })
    verify("Bearer and instance travel together on protected HTTPS", api.get("/api/conversation").str("identity") == "matched")
    val forbidden = fails("403 returned without invalidating credential") { api.get("/api/forbidden") }
    verify("403 preserves credential callback", forbidden is ApiError && forbidden.status == 403 && invalid == 0)
    fails("401 expires only the current credential") { api.get("/api/expired") }
    verify("401 invokes invalidation once", invalid == 1)
    fails("instance mismatch 409 is isolated") { api.get("/api/wrong-instance") }
    verify("instance mismatch invokes invalidation", invalid == 2)
    fails("other 409 does not silently erase credential") { api.get("/api/other-conflict") }
    verify("ordinary conflict preserves credential", invalid == 2)
    fails("missing instance reports 428") { verifier.get("/api/conversation") }
    fails("302 is not followed and authorization is not forwarded") { api.get("/api/redirect") }
    verify("redirect target was never requested", api.get("/api/stats").optInt("redirect_hits") == 0)
    fails("trusted certificate still requires matching hostname") { EchoApi(wrongHostname,DeviceAuthorization(token)).get("/api/paired-device") }
    val epoch = ConnectionEpoch(); val captured = epoch.value
    val oldApi = EchoApi(origin,DeviceAuthorization(token,"instance-a"),requireCurrent={epoch.requireCurrent(captured)},onInvalidCredential={error("stale unauthorized callback must not fire")})
    epoch.advance()
    fails("old generation rejected before sending") { oldApi.get("/api/conversation") }
    verify("generation rejection did not reach server", api.get("/api/stats").optInt("conversation_hits") == 2)
    val current = epoch.value
    val lateApi = EchoApi(origin,DeviceAuthorization(token,"instance-a"),requireCurrent={epoch.requireCurrent(current)},onInvalidCredential={error("old401 invalidated new connection")})
    val delayed = async(Dispatchers.Default) { runCatching { lateApi.get("/api/delayed401") } }
    api.get("/api/wait-started")
    epoch.advance()
    api.get("/api/release")
    verify("late401 discarded by generation guard before invalidation", delayed.await().exceptionOrNull() is IllegalStateException)
    println("PAIRING_TRANSPORT_SYNTHETIC_HTTPS_OK: $count checks; no Android/Keystore/real account execution")
}
