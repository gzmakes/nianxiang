package cn.xinji.echo

import kotlinx.coroutines.runBlocking
import java.time.Instant
import java.time.LocalDate
import org.json.JSONObject

/** Actual native transport to the isolated real paired HTTPS ASGI entrance. */
fun main(args: Array<String>) = runBlocking {
    val origin=args[0]; val token=args[1]; val phase=args[2]; var checks=0
    fun verify(value:Boolean,label:String){check(value){label};checks++;println("PASS $label")}
    suspend fun rejected(status:Int,code:String,api:EchoApi,path:String,method:String="GET",body:JSONObject?=null){val error=try{api.call(method,path,body);null}catch(e:ApiError){e};verify(error?.status==status&&error.code==code,"$status $code $path")}
    if(phase=="revoked"){
        var invalid=0;val api=EchoApi(origin,DeviceAuthorization(token,args[3]),onInvalidCredential={invalid++})
        rejected(401,"paired_authentication_required",api,"/api/conversation");verify(invalid==1,"revoked credential triggers one invalidation")
        println("PAIRED_BACKEND_HTTPS_OK: $checks checks ($phase); JDK host, not Android runtime");return@runBlocking
    }
    val verifier=EchoApi(origin,DeviceAuthorization(token));val credential=PairingPolicy.verify(origin,token,verifier.get("/api/paired-device"))
    val profile=credential.profile;verify(profile.deviceId==args[3],"paired receipt belongs to issued synthetic device")
    var invalid=0;val api=EchoApi(origin,DeviceAuthorization(token,profile.serviceInstanceId),onInvalidCredential={invalid++})
    val encrypted = mutableMapOf<String,String>()
    val store = object : VaultStorage {
        override val names get() = encrypted.keys.toSet()
        override fun get(name:String) = encrypted[name]
        override fun commit(changes:Map<String,String?>,blocked:Boolean?,endpoint:String?):Boolean { changes.forEach{(key,value)->if(value==null)encrypted.remove(key) else encrypted[key]=value};return true }
    }
    val key=javax.crypto.KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
    val vault=DeviceVault(store,object:VaultKeyProvider{override fun key(create:Boolean)=key})
    vault.activate(credential);vault.write("data:pending-${profile.scope}","frozen-id-and-original-body")
    val switched=credential.copy(profile=profile.copy(credentialGeneration="synthetic-different-generation"));vault.activate(switched,profile)
    val archived=vault.savedCredential(profile)!!
    val online=PairingPolicy.verify(origin,archived.token,EchoApi(origin,DeviceAuthorization(archived.token)).get("/api/paired-device"))
    val restored=PairingPolicy.restore(online,vault.savedProfiles().single());vault.activate(restored,switched.profile)
    verify(restored.profile.scope==profile.scope,"explicit restore verifies real original identity before reusing generation")
    verify(vault.read("data:pending-${restored.profile.scope}")=="frozen-id-and-original-body","restore retains exact unknown body and does not replay it")
    val other=PairingPolicy.verify(origin,args[4],EchoApi(origin,DeviceAuthorization(args[4])).get("/api/paired-device"))
    val refused=runCatching{PairingPolicy.restore(other,profile)}.isFailure
    verify(refused&&vault.read("data:pending-${profile.scope}")=="frozen-id-and-original-body","another real paired device cannot adopt the original unknown namespace")
    val current=conversation(api.get("/api/conversation"));verify(current.id==profile.conversationId,"same canonical conversation over HTTPS")
    val caps=api.get("/api/capabilities");verify(caps.str("deployment_mode")=="paired_single_owner"&&caps.opt("local_actions_allowed")==false,"paired capabilities declare single owner and no local actions")
    verify(caps.getJSONObject("features").opt("bounded_followup_contact")==false&&caps.getJSONObject("features").opt("unified_contact_claim")==false,"remote does not promise autonomous or OS contact")
    val sources=api.get("/api/onboarding/sources").rows("sources");verify(sources.size==1&&sources.single().str("id")=="local_files","safe source catalog does not probe CLI")
    val created=memory(api.post("/api/memory",json("session_id" to current.id,"kind" to "fact","text" to "合成手机候选记忆","source" to "用户手动添加")))
    verify(created.status=="candidate"&&created.text=="合成手机候选记忆","remote memory create remains candidate")
    verify(conversation(api.get("/api/conversation")).memories.any{it.id==created.id},"remote reads saved candidate")
    verify(api.get("/api/memory/${encoded(created.id)}/history").rows("revisions").isNotEmpty(),"remote memory history ownership path")
    api.call("DELETE",memoryDeletePath(created));verify(conversation(api.get("/api/conversation")).memories.none{it.id==created.id},"remote expected-version delete applied")
    val day=LocalDate.now().toString();val operation=MoodOperation("synthetic-android-mood",json("kind" to "save","date" to day,"expected_updated_at" to JSONObject.NULL,"x" to .25,"y" to -.2,"note" to "合成手机原话").toString(),"save")
    val moodReceipt=moodOperationReceipt(api.post("/api/mood-operations",operation.applyBody(current.id)),current.id,operation)
    verify(moodReceipt.state=="applied","remote mood ledger applied exact frozen operation")
    verify(moodOperationReceipt(api.get("/api/mood-operations/${operation.requestId}?session_id=${encoded(current.id)}"),current.id,operation)==moodReceipt,"remote mood operation query matches identity")
    verify(moodRecords(api.get("/api/moods?session_id=${encoded(current.id)}")).any{it.date==day&&it.note=="合成手机原话"},"remote diary has independent current record")
    val followup=followup(api.post("/api/followups",json("session_id" to current.id,"request_id" to "synthetic-android-followup","content" to "合成稍后核对","due_at" to Instant.now().plusSeconds(3600).toString(),"confirmed" to true,"allow_contact" to false,"time_zone" to "Asia/Shanghai")))
    verify(followup.sessionId==current.id&&followup.status=="pending","remote saves passive followup without contact permission")
    verify(followups(api.get("/api/followups?session_id=${encoded(current.id)}")).any{it.id==followup.id},"remote passive followup list")
    verify(companionBoundary(api.get("/api/companion-boundary?session_id=${encoded(current.id)}")).mode in listOf("active","paused","until"),"remote reads shared companion boundary")
    rejected(403,"paired_operation_forbidden",api,"/api/actions?session_id=${encoded(current.id)}")
    rejected(403,"paired_operation_forbidden",api,"/api/action","POST",json("session_id" to current.id,"kind" to "reminder","real" to false))
    rejected(403,"paired_operation_forbidden",api,"/api/feishu/read","POST",json("session_id" to current.id,"url" to "https://example.invalid/synthetic"))
    rejected(403,"paired_operation_forbidden",api,"/api/settings")
    rejected(403,"paired_operation_forbidden",api,"/api/notifications/settings")
    rejected(403,"paired_operation_forbidden",api,"/api/moods?session_id=another-owner")
    verify(invalid==0,"forbidden operations do not erase valid paired credential")
    rejected(428,"service_instance_required",verifier,"/api/conversation")
    rejected(409,"service_instance_mismatch",EchoApi(origin,DeviceAuthorization(token,"svc_other")),"/api/conversation")
    rejected(401,"paired_authentication_required",EchoApi(origin),"/api/conversation")
    println("PAIRED_BACKEND_HTTPS_OK: $checks checks ($phase); JDK host, not Android runtime")
}
