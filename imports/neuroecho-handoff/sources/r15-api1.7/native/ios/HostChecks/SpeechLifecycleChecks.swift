import Foundation
import SwiftUI

@MainActor private final class SyntheticSpeechDriver: EchoSpeechDriver {
    var isAvailable=true
    var throwOnStart=false
    var stopConfirmed=true
    var starts=[EchoSpeechRequest]()
    var stops=0
    var handlers=[UUID:@Sendable(EchoSpeechEvent)->Void]()
    func start(_ request: EchoSpeechRequest,onEvent: @escaping @Sendable (EchoSpeechEvent)->Void) throws {
        starts.append(request);handlers[request.token]=onEvent
        if throwOnStart {throw EchoAPIError.message("synthetic start failure")}
    }
    func stop() -> Bool {stops += 1;return stopConfirmed}
    func emit(_ event: EchoSpeechEvent) {handlers[event.token]?(event)}
}
@main struct SpeechLifecycleChecks {
    static func message(_ id: String = "one",role: String = "assistant",text: String = "可见正文",parts: [String]? = nil,pending: Bool? = nil) throws -> EchoMessage {
        var obj:[String:Any] = ["id":id,"role":role,"text":text]
        if let parts {obj["bubbles"]=parts};if let pending {obj["delivery_pending"]=pending}
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(EchoMessage.self,from:JSONSerialization.data(withJSONObject:obj))
    }
    @MainActor static func settle() async {for _ in 0..<40 {await Task.yield()}}
    @MainActor static func main() async {
        var count=0
        func pass(_ s: String) {count += 1;print("PASS:",s)}
        do {
            let driver=SyntheticSpeechDriver(),model=SpeechController(driver:driver),one=try message(),two=try message("two",text:"另一条已见回复")
            model.reconcile(messages:[one],origin:"local",sessionID:"one",foreground:true)
            model.toggle(try message(role:"user"),origin:"local",sessionID:"one",foreground:true)
            model.toggle(try message(text:"隐藏",parts:["可见"],pending:true),origin:"local",sessionID:"one",foreground:true)
            model.toggle(one,origin:"local",sessionID:"one",foreground:false)
            precondition(driver.starts.isEmpty && model.active == nil)
            pass("bind/refresh/user/pending/background never starts speech without eligible explicit tap")
            model.toggle(one,origin:"local",sessionID:"one",foreground:true);let first=model.active!
            precondition(first.phase == .preparing && driver.starts.count == 1)
            driver.emit(.started(first.token));await settle();precondition(model.active?.phase == .speaking)
            driver.emit(.finished(first.token));await settle();precondition(model.active == nil)
            pass("actual controller progresses preparing -> started -> finished only with matching immutable token")
            model.toggle(one,origin:"local",sessionID:"one",foreground:true);let old=model.active!,beforeStop=driver.stops
            model.toggle(one,origin:"local",sessionID:"one",foreground:true)
            precondition(model.active == nil && driver.stops == beforeStop+1)
            driver.emit(.started(old.token));driver.emit(.cancelled(old.token));await settle();precondition(model.active == nil)
            pass("second tap requests immediate stop and invalidates first; late start/cancel never resumes")
            model.toggle(one,origin:"local",sessionID:"one",foreground:true);let previous=model.active!
            model.toggle(two,origin:"local",sessionID:"one",foreground:true);let latest=model.active!
            for event in [EchoSpeechEvent.started(previous.token),.finished(previous.token),.cancelled(previous.token),.failed(previous.token)] {driver.emit(event)}
            await settle();precondition(model.active?.token == latest.token && latest.target.messageID == "two" && driver.starts.last?.target.speechText == "另一条已见回复")
            driver.emit(.started(latest.token));await settle();precondition(model.active?.phase == .speaking)
            pass("new tap stops old request; delayed old delegate events cannot clear or modify the new request")
            let parts=try message(text:"包含隐藏后段",parts:["只读可见段"])
            model.toggle(parts,origin:"local",sessionID:"one",foreground:true)
            precondition(driver.starts.last?.target.speechText == "只读可见段" && !driver.starts.last!.target.speechText.contains("隐藏后段"))
            model.reconcile(messages:[try message(text:"底层全文已改",parts:["只读可见段"])],origin:"local",sessionID:"one",foreground:true)
            precondition(model.active == nil)
            pass("legacy bubbles use visible parts only; even hidden raw-text mutation invalidates the old reading")
            let cases:[([EchoMessage],String,String?,Bool)]=[([],"local","one",true),([one],"other","one",true),([one],"local","two",true),([one],"local",nil,true),([one],"local","one",false),([try message(text:"修改正文")],"local","one",true),([try message(pending:true)],"local","one",true)]
            for (messages,origin,sid,foreground) in cases {
                model.toggle(one,origin:"local",sessionID:"one",foreground:true);precondition(model.active != nil)
                let stopCount=driver.stops;model.reconcile(messages:messages,origin:origin,sessionID:sid,foreground:foreground)
                precondition(model.active == nil && driver.stops == stopCount+1)
                model.reconcile(messages:[one],origin:"local",sessionID:"one",foreground:true);precondition(model.active == nil)
            }
            pass("service/sid/foreground/deletion/topic-hidden/content/pending change stop, and later refresh never auto resumes")
            model.toggle(one,origin:"local",sessionID:"one",foreground:true);let preserved=model.active!
            model.reconcile(messages:[one],origin:"local",sessionID:"one",foreground:true);precondition(model.active?.token == preserved.token)
            model.preparationTimedOut(token:UUID());precondition(model.active?.token == preserved.token)
            driver.emit(.started(preserved.token));await settle();model.preparationTimedOut(token:preserved.token)
            precondition(model.active?.phase == .speaking)
            _=model.stop();model.toggle(two,origin:"local",sessionID:"one",foreground:true);let timeout=model.active!
            model.preparationTimedOut(token:timeout.token);precondition(model.active == nil && model.unavailableMessageID == "two")
            driver.emit(.started(timeout.token));await settle();precondition(model.active == nil)
            pass("unchanged refresh keeps playback; preparation timeout is token/phase bound and late start stays invalid")
            driver.isAvailable=false;let before=driver.starts.count
            model.toggle(one,origin:"local",sessionID:"one",foreground:true)
            precondition(model.active == nil && model.unavailableMessageID == "one" && driver.starts.count == before)
            model.reconcile(messages:[one],origin:"different",sessionID:"one",foreground:true);precondition(model.unavailableMessageID == nil)
            driver.isAvailable=true;driver.throwOnStart=true;model.toggle(one,origin:"local",sessionID:"one",foreground:true)
            precondition(model.active == nil && model.unavailableMessageID == "one");driver.throwOnStart=false
            model.toggle(one,origin:"local",sessionID:"one",foreground:true);let failed=model.active!
            driver.emit(.failed(failed.token));await settle();precondition(model.active == nil && model.unavailableMessageID == "one")
            pass("unavailable voice or start failure leaves text usable, no claimed playback, and notices cannot cross service scope")
            model.toggle(one,origin:"local",sessionID:"one",foreground:true);let oldCount=driver.starts.count
            driver.stopConfirmed=false;model.toggle(two,origin:"local",sessionID:"one",foreground:true)
            precondition(model.active == nil && driver.starts.count == oldCount && model.unavailableMessageID == "two")
            driver.stopConfirmed=true;model.toggle(two,origin:"local",sessionID:"one",foreground:true)
            precondition(model.active?.target.messageID == "two" && driver.starts.count == oldCount+1)
            _=model.stop()
            pass("unconfirmed driver stop prevents overlapping new playback; another explicit tap can retry after stop is confirmed")
            print("Speech controller checks:",count,"/",count,"passed; actual controller + replaceable synthetic driver on macOS; no audio output/network/microphone/iOS SDK.")
        } catch {print("FAIL:",error.localizedDescription);exit(1)}
    }
}
