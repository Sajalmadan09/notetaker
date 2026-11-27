// Native meeting recorder: the browser's audio (other participants) via a Core Audio process
// tap, and the user's voice from the Mac's built-in mic, as two 16 kHz mono tracks.
// Started/stopped by the Kiroku app over stdin ("meeting-start <id> <dir>" / "meeting-stop").
import AVFoundation
import AudioToolbox
import CoreAudio
import Foundation

// MARK: - Core Audio property helpers

private func getProp<T>(_ obj: AudioObjectID, _ selector: AudioObjectPropertySelector,
                        scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal, _ initial: T) -> T? {
    var addr = AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
    var value = initial
    var size = UInt32(MemoryLayout<T>.size)
    return AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &value) == noErr ? value : nil
}

private func getArray(_ obj: AudioObjectID, _ selector: AudioObjectPropertySelector,
                      scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> [AudioObjectID] {
    var addr = AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(obj, &addr, 0, nil, &size) == noErr, size > 0 else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    return AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &ids) == noErr ? ids : []
}

private func getString(_ obj: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
    var addr = AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
                                          mElement: kAudioObjectPropertyElementMain)
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &value) == noErr, let v = value else { return nil }
    return v.takeRetainedValue() as String
}

/// The Mac's built-in microphone. "Default input" follows macOS, which can switch to a nearby
/// iPhone (Continuity) whose mic drops out mid-meeting, so the built-in mic is pinned by device.
func builtInMicDevice() -> AudioDeviceID? {
    for dev in getArray(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyDevices) {
        let inputs = getArray(dev, kAudioDevicePropertyStreams, scope: kAudioObjectPropertyScopeInput)
        let transport: UInt32? = getProp(dev, kAudioDevicePropertyTransportType, UInt32(0))
        if !inputs.isEmpty && transport == kAudioDeviceTransportTypeBuiltIn { return dev }
    }
    return nil
}

func deviceName(_ dev: AudioDeviceID) -> String { getString(dev, kAudioObjectPropertyName) ?? "unknown" }

// MARK: - 16 kHz mono accumulation

final class Track {
    private var samples: [Float] = []
    private let lock = NSLock()
    private var recentSq: Float = 0, recentN = 0

    /// Mix `channels` (non-interleaved pointers, or one interleaved buffer) to mono and resample.
    func append(_ read: (Int, Int) -> Float, frames n: Int, channels: Int, rate: Double) {
        guard n > 0, channels > 0 else { return }
        let ratio = rate / 16000.0
        let count = Int(Double(n) / ratio)
        var out = [Float](repeating: 0, count: count)
        for j in 0..<count {
            let i = min(n - 1, Int(Double(j) * ratio))
            var s: Float = 0
            for c in 0..<channels { s += read(i, c) }
            out[j] = s / Float(channels)
        }
        lock.lock()
        samples.append(contentsOf: out)
        for s in out { recentSq += s * s }
        recentN += out.count
        lock.unlock()
    }

    /// RMS since the last call (for level meters).
    func takeLevel() -> Float {
        lock.lock(); defer { recentSq = 0; recentN = 0; lock.unlock() }
        return recentN == 0 ? 0 : (recentSq / Float(recentN)).squareRoot()
    }

    func take() -> [Float] { lock.lock(); defer { lock.unlock() }; return samples }
}

func appendBufferList(_ abl: UnsafePointer<AudioBufferList>, format f: AudioStreamBasicDescription, to track: Track) {
    let list = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: abl))
    guard f.mFormatID == kAudioFormatLinearPCM, f.mFormatFlags & kAudioFormatFlagIsFloat != 0, f.mBitsPerChannel == 32,
          let first = list.first, first.mData != nil else { return }
    let nonInterleaved = f.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
    if nonInterleaved {
        let chans = list.count
        let frames = Int(first.mDataByteSize) / 4
        let ptrs = list.map { $0.mData!.assumingMemoryBound(to: Float.self) }
        track.append({ i, c in ptrs[c][i] }, frames: frames, channels: chans, rate: f.mSampleRate)
    } else {
        let chans = Int(max(1, first.mNumberChannels))
        let frames = Int(first.mDataByteSize) / 4 / chans
        let p = first.mData!.assumingMemoryBound(to: Float.self)
        track.append({ i, c in p[i * chans + c] }, frames: frames, channels: chans, rate: f.mSampleRate)
    }
}

// MARK: - Browser audio via a process tap (macOS 14.4+)

@available(macOS 14.4, *)
final class ProcessTap {
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var aggID = AudioObjectID(kAudioObjectUnknown)
    private var procID: AudioDeviceIOProcID?
    private(set) var source = ""

    static let browsers = ["com.google.Chrome", "com.microsoft.edgemac", "com.brave.Browser",
                           "company.thebrowser.Browser", "com.apple.Safari", "com.apple.WebKit", "org.mozilla.firefox"]

    /// Audio process objects of running browsers (Chrome plays audio from a helper process).
    static func browserProcesses() -> [AudioObjectID] {
        getArray(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyProcessObjectList).filter { obj in
            let bundle = getString(obj, kAudioProcessPropertyBundleID) ?? ""
            return browsers.contains { bundle.hasPrefix($0) }
        }
    }

    func start(into track: Track) throws {
        let procs = ProcessTap.browserProcesses()
        // No browser audio process yet (nothing played): fall back to all system audio except Kiroku.
        let desc = procs.isEmpty ? CATapDescription(stereoGlobalTapButExcludeProcesses: [])
                                 : CATapDescription(stereoMixdownOfProcesses: procs)
        source = procs.isEmpty ? "all system audio" : "browser (\(procs.count) audio process\(procs.count == 1 ? "" : "es"))"
        desc.uuid = UUID()
        desc.name = "Kiroku meeting audio"
        desc.isPrivate = true
        desc.muteBehavior = .unmuted
        var err = AudioHardwareCreateProcessTap(desc, &tapID)
        guard err == noErr else { throw NSError(domain: "tap", code: Int(err), userInfo: [NSLocalizedDescriptionKey: "process tap failed (\(err)); allow System Audio Recording for Kiroku"]) }

        guard let format: AudioStreamBasicDescription = getProp(tapID, kAudioTapPropertyFormat, AudioStreamBasicDescription()) else {
            throw NSError(domain: "tap", code: 1, userInfo: [NSLocalizedDescriptionKey: "tap format unavailable"])
        }
        let out: AudioDeviceID = getProp(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyDefaultOutputDevice, AudioDeviceID(0)) ?? 0
        let outUID = getString(out, kAudioDevicePropertyDeviceUID) ?? ""
        let agg: [String: Any] = [
            kAudioAggregateDeviceNameKey: "Kiroku Tap",
            kAudioAggregateDeviceUIDKey: UUID().uuidString,
            kAudioAggregateDeviceMainSubDeviceKey: outUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outUID]],
            kAudioAggregateDeviceTapListKey: [[kAudioSubTapDriftCompensationKey: true, kAudioSubTapUIDKey: desc.uuid.uuidString]],
        ]
        err = AudioHardwareCreateAggregateDevice(agg as CFDictionary, &aggID)
        guard err == noErr else { throw NSError(domain: "tap", code: Int(err), userInfo: [NSLocalizedDescriptionKey: "aggregate device failed (\(err))"]) }
        let queue = DispatchQueue(label: "kiroku.tap", qos: .userInitiated)
        err = AudioDeviceCreateIOProcIDWithBlock(&procID, aggID, queue) { _, input, _, _, _ in
            appendBufferList(input, format: format, to: track)
        }
        guard err == noErr else { throw NSError(domain: "tap", code: Int(err), userInfo: [NSLocalizedDescriptionKey: "tap IO proc failed (\(err))"]) }
        err = AudioDeviceStart(aggID, procID)
        guard err == noErr else { throw NSError(domain: "tap", code: Int(err), userInfo: [NSLocalizedDescriptionKey: "tap start failed (\(err)); allow System Audio Recording for Kiroku"]) }
    }

    func stop() {
        if aggID != kAudioObjectUnknown {
            if let p = procID { AudioDeviceStop(aggID, p); AudioDeviceDestroyIOProcID(aggID, p) }
            AudioHardwareDestroyAggregateDevice(aggID)
        }
        if tapID != kAudioObjectUnknown { AudioHardwareDestroyProcessTap(tapID) }
        aggID = AudioObjectID(kAudioObjectUnknown); tapID = AudioObjectID(kAudioObjectUnknown); procID = nil
    }
}

// MARK: - The user's voice from the built-in mic

final class MeetingMic {
    private var engine = AVAudioEngine()
    private(set) var device = ""
    private(set) var echoCancellation = false

    private func pin(_ dev: AudioDeviceID) -> Bool {
        guard let unit = engine.inputNode.audioUnit else { return false }
        var id = dev
        return AudioUnitSetProperty(unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0,
                                    &id, UInt32(MemoryLayout<AudioDeviceID>.size)) == noErr
    }

    private func current() -> AudioDeviceID? {
        guard let unit = engine.inputNode.audioUnit else { return nil }
        var id = AudioDeviceID(0)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        return AudioUnitGetProperty(unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &id, &size) == noErr ? id : nil
    }

    private func run(into track: Track, voiceProcessing: Bool, pinTo dev: AudioDeviceID?) throws {
        engine = AVAudioEngine()
        let input = engine.inputNode
        if voiceProcessing {
            try input.setVoiceProcessingEnabled(true)
            if #available(macOS 14.0, *) {  // don't turn the meeting down while we listen
                input.voiceProcessingOtherAudioDuckingConfiguration =
                    AVAudioVoiceProcessingOtherAudioDuckingConfiguration(enableAdvancedDucking: false, duckingLevel: .min)
            }
        } else if let d = dev {
            _ = pin(d)
        }
        let fmt = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 4096, format: fmt) { buffer, _ in
            guard let ch = buffer.floatChannelData?[0] else { return }
            track.append({ i, _ in ch[i] }, frames: Int(buffer.frameLength), channels: 1, rate: fmt.sampleRate)
        }
        do { try engine.start() } catch { input.removeTap(onBus: 0); throw error }
        echoCancellation = voiceProcessing
        // With voice processing the unit reports the paired output; the mic is the default input.
        let dflt: AudioDeviceID? = getProp(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyDefaultInputDevice, AudioDeviceID(0))
        device = (voiceProcessing ? dflt : current()).map(deviceName) ?? "default input"
    }

    /// Echo cancellation (so the other people coming out of the speakers aren't transcribed twice)
    /// only works on macOS's default devices. Use it when the default mic is the built-in one;
    /// otherwise (e.g. an iPhone took over as default) pin the built-in mic without it.
    func start(into track: Track) throws {
        let builtIn = builtInMicDevice()
        let defaultIn: AudioDeviceID? = getProp(AudioObjectID(kAudioObjectSystemObject),
                                                kAudioHardwarePropertyDefaultInputDevice, AudioDeviceID(0))
        if builtIn == nil || builtIn == defaultIn {
            do { return try run(into: track, voiceProcessing: true, pinTo: nil) }
            catch { trace(["event": "meeting_mic_vp_failed", "error": "\(error)"]) }
        }
        try run(into: track, voiceProcessing: false, pinTo: builtIn)
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }
}

// MARK: - Session

final class MeetingSession {
    let id: String
    let dir: URL
    let mic = Track(), others = Track()
    private let micRec = MeetingMic()
    private var tap: AnyObject?
    private var meter: DispatchSourceTimer?
    private var stopped = false
    private let queue = DispatchQueue(label: "kiroku.meeting")  // all session state lives here

    init(id: String, dir: URL) { self.id = id; self.dir = dir }

    /// Mic first, reported at once. The browser tap starts only after the mic is running and on
    /// another queue: its first use waits on macOS's "record system audio" permission, holding
    /// Core Audio meanwhile, and that must never block the mic or a stop.
    func start() {
        queue.async { [self] in
            var info: [String: Any] = ["event": "started"]
            do { try micRec.start(into: mic); info["mic"] = micRec.device; info["echo_cancellation"] = micRec.echoCancellation }
            catch { info["mic_error"] = error.localizedDescription }
            trace(["event": "meeting_start", "id": id, "info": info])
            report(info)
            let t = DispatchSource.makeTimerSource(queue: queue)
            t.schedule(deadline: .now() + 2, repeating: 2)
            t.setEventHandler { [weak self] in
                guard let self else { return }
                self.report(["event": "levels", "mic": self.mic.takeLevel(), "others": self.others.takeLevel()])
            }
            t.resume()
            meter = t
            startTap()
        }
    }

    private func startTap() {
        guard #available(macOS 14.4, *) else {
            report(["event": "others", "others_error": "recording meeting audio needs macOS 14.4 or newer"])
            return
        }
        DispatchQueue.global(qos: .userInitiated).async { [self] in
            let t = ProcessTap()
            do {
                try t.start(into: others)
                queue.async { [self] in
                    if stopped { t.stop(); return }
                    tap = t
                    trace(["event": "meeting_tap", "id": id, "source": t.source])
                    report(["event": "others", "others": t.source])
                }
            } catch {
                trace(["event": "meeting_tap_failed", "id": id, "error": error.localizedDescription])
                report(["event": "others", "others_error": error.localizedDescription])
            }
        }
    }

    func stop() {
        queue.async { [self] in
            stopped = true
            meter?.cancel()
            micRec.stop()
            if #available(macOS 14.4, *) { (tap as? ProcessTap)?.stop() }
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            var a = mic.take(), b = others.take()
            let n = max(a.count, b.count)  // both started together; pad the shorter one at the end
            a += [Float](repeating: 0, count: n - a.count)
            b += [Float](repeating: 0, count: n - b.count)
            var info: [String: Any] = ["event": "finished", "seconds": Double(n) / 16000]
            do {
                try wavData(a).write(to: dir.appendingPathComponent("mic.wav"))
                try wavData(b).write(to: dir.appendingPathComponent("others.wav"))
            } catch { info = ["event": "error", "error": "couldn't save the recording: \(error.localizedDescription)"] }
            trace(["event": "meeting_stop", "id": id, "seconds": Double(n) / 16000])
            report(info)
        }
    }

    private func report(_ body: [String: Any]) {
        var r = URLRequest(url: URL(string: serverURL + "/api/meeting/\(id)/event")!)
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: r).resume()
    }
}

var currentMeeting: MeetingSession?

/// Commands from the Kiroku app on stdin. Runs on the main thread.
func handleCommand(_ line: String) {
    let parts = line.split(separator: " ", maxSplits: 2).map(String.init)
    switch parts.first {
    case "meeting-start" where parts.count == 3:
        currentMeeting?.stop()
        let s = MeetingSession(id: parts[1], dir: URL(fileURLWithPath: parts[2]))
        currentMeeting = s
        s.start()
    case "meeting-stop":
        currentMeeting?.stop()
        currentMeeting = nil
    default:
        trace(["event": "unknown_command", "line": line])
    }
}

func listenForCommands() {
    Thread.detachNewThread {
        while let line = readLine() {
            let cmd = line.trimmingCharacters(in: .whitespaces)
            if !cmd.isEmpty { DispatchQueue.main.async { handleCommand(cmd) } }
        }
    }
}
