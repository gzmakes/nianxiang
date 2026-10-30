import AVFoundation
import Foundation

/// This test writes synthetic speech into a temporary WAV. It never calls speak,
/// plays a speaker, uses a microphone, or reads any conversation/user text.
private final class BufferCapture: @unchecked Sendable {
    private let lock=NSLock()
    private var writer: AVAudioFile?
    private var error: String?
    private var total: AVAudioFramePosition=0
    private var ended=false
    let url: URL
    init(url: URL) {self.url=url}
    func append(_ buffer: AVAudioBuffer) {
        lock.lock();defer {lock.unlock()}
        guard let pcm=buffer as? AVAudioPCMBuffer else {error="non-PCM buffer";ended=true;return}
        if pcm.frameLength == 0 {ended=true;writer=nil;return}
        do {
            if writer == nil {
                let settings:[String:Any] = [AVFormatIDKey:kAudioFormatLinearPCM,AVSampleRateKey:pcm.format.sampleRate,AVNumberOfChannelsKey:pcm.format.channelCount,AVLinearPCMBitDepthKey:16,AVLinearPCMIsFloatKey:false,AVLinearPCMIsBigEndianKey:false]
                writer=try AVAudioFile(forWriting:url,settings:settings,commonFormat:pcm.format.commonFormat,interleaved:pcm.format.isInterleaved)
            }
            try writer!.write(from:pcm);total += AVAudioFramePosition(pcm.frameLength)
        } catch {self.error="audio buffer write failed";ended=true;writer=nil}
    }
    var snapshot: (Bool,AVAudioFramePosition,String?) {lock.lock();defer {lock.unlock()};return (ended,total,error)}
    func close() {lock.lock();defer {lock.unlock()};writer=nil}
}
@main struct SpeechBufferSmoke {
    @MainActor static func main() {
        let directory=URL(fileURLWithPath:CommandLine.arguments.first!).deletingLastPathComponent()
        guard directory.lastPathComponent == "host-checks",directory.deletingLastPathComponent().lastPathComponent == ".build" else {print("NOT_RUN: require isolated .build/host-checks executable");exit(2)}
        let output=directory.appendingPathComponent("r12-synthetic-system-speech-"+UUID().uuidString+".wav")
        defer {try? FileManager.default.removeItem(at:output)}
        let voices=EchoSystemSpeechDriver.availableVoices()
        let chinese=voices.first {$0.language == "zh-CN" && $0.quality == .default} ?? voices.first {$0.language == "zh-CN"} ?? voices.first {$0.language.hasPrefix("zh")}
        guard let voice=chinese ?? voices.first(where:{$0.language == "en-US" && $0.quality == .default}) else {print("NOT_COVERED: no available Apple system voice; no download or authorization attempted.");return}
        let synthesizer=AVSpeechSynthesizer(),text=chinese == nil ? "This is a synthetic reading check." : "这是一段合成朗读检查。"
        let utterance=AVSpeechUtterance(string:text);utterance.voice=voice
        let capture=BufferCapture(url:output)
        print("HOST_AVFOUNDATION_BUFFER: write-only synthetic text, voice language",voice.language,"no speaker / iOS runtime / microphone / app server.")
        synthesizer.write(utterance) {buffer in capture.append(buffer)}
        let deadline=Date().addingTimeInterval(15)
        while !capture.snapshot.0 && Date() < deadline {_ = RunLoop.current.run(mode:.default,before:Date().addingTimeInterval(0.05))}
        let snapshot=capture.snapshot;capture.close()
        guard snapshot.0,snapshot.1 > 0,snapshot.2 == nil else {
            _=synthesizer.stopSpeaking(at:.immediate)
            print("NOT_COVERED: host write did not complete valid PCM within15s; frames",snapshot.1,"error",snapshot.2 ?? "none","no audibility claim.");return
        }
        do {
            let data=try Data(contentsOf:output),file=try AVAudioFile(forReading:output)
            guard data.count > 44,String(data:data.prefix(4),encoding:.ascii) == "RIFF",String(data:data[8..<12],encoding:.ascii) == "WAVE",file.length == snapshot.1 else {fatalError("Invalid generated WAV")}
            let buffer=AVAudioPCMBuffer(pcmFormat:file.processingFormat,frameCapacity:AVAudioFrameCount(file.length))!
            try file.read(into:buffer)
            let audibleSamples=(buffer.floatChannelData.map {channels in (0..<Int(buffer.frameLength)).contains {abs(channels[0][$0]) > 0.00001}}) ?? false
            precondition(audibleSamples,"Generated buffer must include nonzero samples")
            print("PASS: actual AVSpeechSynthesizer.write produced RIFF/WAVE PCM16",data.count,"bytes",file.length,"frames, nonzero samples; temporary WAV removed. This is synthesis only, NOT speaker or iOS device verification.")
        } catch {print("FAIL: generated audio could not be decoded");exit(1)}
    }
}
