import SwiftUI
import AVFoundation

/// The replaceable device boundary. No server client or microphone API exists here.
@MainActor protocol EchoSpeechDriver: AnyObject {
    var isAvailable: Bool {get}
    func start(_ request: EchoSpeechRequest,onEvent: @escaping @Sendable (EchoSpeechEvent) -> Void) throws
    @discardableResult func stop() -> Bool
}

/// One immutable token/delegate per utterance; callbacks never consult a mutable
/// "current token" and therefore cannot accidentally identify a newer utterance.
private final class EchoSystemUtterance: NSObject, AVSpeechSynthesizerDelegate, @unchecked Sendable {
    let token: UUID
    let synthesizer=AVSpeechSynthesizer()
    let utterance: AVSpeechUtterance
    let onEvent: @Sendable (EchoSpeechEvent) -> Void
    init(request: EchoSpeechRequest,voice: AVSpeechSynthesisVoice,onEvent: @escaping @Sendable (EchoSpeechEvent) -> Void) {
        token=request.token;utterance=AVSpeechUtterance(string:request.target.speechText);self.onEvent=onEvent
        super.init()
        utterance.voice=voice;utterance.rate=AVSpeechUtteranceDefaultSpeechRate * 0.96
        #if os(iOS)
        // Let the synthesizer own its playback-only session; no record category,
        // microphone permission, telephony uplink or background-audio mode.
        synthesizer.usesApplicationAudioSession=false
        #endif
        synthesizer.delegate=self
    }
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,didStart utterance: AVSpeechUtterance) {if utterance === self.utterance {onEvent(.started(token))}}
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,didFinish utterance: AVSpeechUtterance) {if utterance === self.utterance {onEvent(.finished(token))}}
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,didCancel utterance: AVSpeechUtterance) {if utterance === self.utterance {onEvent(.cancelled(token))}}
}

@MainActor final class EchoSystemSpeechDriver: EchoSpeechDriver {
    private var current: EchoSystemUtterance?
    /// Use an available Apple system voice, never request Personal Voice access
    /// or select a third-party speech provider whose data routing is unknown.
    static func availableVoices() -> [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices().filter {voice in
            guard voice.identifier.hasPrefix("com.apple.") else {return false}
            if #available(iOS 17,macOS 14,*) {return !voice.voiceTraits.contains(.isPersonalVoice)}
            return true
        }
    }
    var isAvailable: Bool {!Self.availableVoices().isEmpty}
    func start(_ request: EchoSpeechRequest,onEvent: @escaping @Sendable (EchoSpeechEvent) -> Void) throws {
        // The controller has already stopped/invalidated the previous request.
        guard current == nil else {throw EchoAPIError.message("上一段朗读仍需停止，请稍后再试。")}
        let voices=Self.availableVoices()
        let voice=voices.first {$0.language == "zh-CN"} ?? voices.first {$0.language.hasPrefix("zh")} ?? voices.first {$0.language == Locale.current.identifier.replacingOccurrences(of:"_",with:"-")} ?? voices.first {$0.language == "en-US"} ?? voices.first
        guard let voice else {throw EchoAPIError.message("设备系统语音暂不可用。")}
        let value=EchoSystemUtterance(request:request,voice:voice,onEvent:onEvent);current=value
        value.synthesizer.speak(value.utterance)
    }
    @discardableResult func stop() -> Bool {
        guard let old=current else {return true}
        let stopped=old.synthesizer.stopSpeaking(at:.immediate)
        // didCancel is not guaranteed for queued/unspoken utterances. Do not wait
        // for it to clear app state, but do not overlap if the system is still busy.
        guard stopped || !old.synthesizer.isSpeaking else {return false}
        old.synthesizer.delegate=nil;current=nil;return true
    }
    func releaseFinished(token: UUID) {if current?.token == token {current?.synthesizer.delegate=nil;current=nil}}
}

@MainActor final class SpeechController: ObservableObject {
    @Published private(set) var state=EchoSpeechState()
    @Published private(set) var unavailableMessageID: String?
    private var unavailableTarget: EchoSpeechTarget?
    private let driver: EchoSpeechDriver
    private var preparing: Task<Void,Never>?
    init(driver: EchoSpeechDriver? = nil) {self.driver=driver ?? EchoSystemSpeechDriver()}
    var active: EchoSpeechRequest? {state.active}
    func toggle(_ message: EchoMessage,origin: String,sessionID: String?,foreground: Bool) {
        guard let target=EchoSpeechTarget.visibleReply(message,origin:origin,sessionID:sessionID,foreground:foreground) else {return}
        if state.active?.target == target {stop();return}
        guard stop() else {markUnavailable(target);return}
        unavailableMessageID=nil;unavailableTarget=nil
        guard driver.isAvailable else {markUnavailable(target);return}
        let request=state.begin(target)
        do {
            try driver.start(request) {[weak self] event in Task {@MainActor in self?.receive(event)}}
            preparing=Task {[weak self] in
                try? await Task.sleep(for:.seconds(10))
                guard !Task.isCancelled else {return}
                self?.preparationTimedOut(token:request.token)
            }
        } catch {state.receive(.failed(request.token));markUnavailable(target)}
    }
    @discardableResult func stop() -> Bool {
        preparing?.cancel();preparing=nil
        state.invalidate() // Invalidate first: a synchronous old callback is stale.
        return driver.stop()
    }
    func reconcile(messages: [EchoMessage],origin: String,sessionID: String?,foreground: Bool) {
        if state.reconcile(messages:messages,origin:origin,sessionID:sessionID,foreground:foreground) {preparing?.cancel();preparing=nil;_ = driver.stop()}
        if let target=unavailableTarget {
            let latest=messages.first {$0.id == target.messageID}.flatMap {EchoSpeechTarget.visibleReply($0,origin:origin,sessionID:sessionID,foreground:foreground)}
            if latest != target {unavailableMessageID=nil;unavailableTarget=nil}
        }
    }
    func receive(_ event: EchoSpeechEvent) {
        let target=state.active?.token == event.token ? state.active?.target : nil
        switch event {
        case .started:break
        case .finished,.cancelled,.failed:(driver as? EchoSystemSpeechDriver)?.releaseFinished(token:event.token)
        }
        guard state.receive(event) else {return}
        preparing?.cancel();preparing=nil
        if case .failed=event,let target {markUnavailable(target)}
    }
    func preparationTimedOut(token: UUID) {
        guard let request=state.active,request.token == token,request.phase == .preparing else {return}
        markUnavailable(request.target);_ = stop()
    }
    private func markUnavailable(_ target: EchoSpeechTarget) {unavailableTarget=target;unavailableMessageID=target.messageID}
}
