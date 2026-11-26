// NotetakerHelper spike: hold Option+Space -> mic -> local int4 ASR (localhost
// server /api/quick) -> AX insertion (pasteboard fallback) -> read-back
// verification -> JSONL trace. Mechanisms per docs/dictation-layer-findings.md;
// implemented with public macOS APIs only.
import AppKit
import AVFoundation
import ApplicationServices
import Carbon
import Foundation

setbuf(stdout, nil)
let serverURL = ProcessInfo.processInfo.environment["NOTETAKER_SERVER"] ?? "http://127.0.0.1:8010"
let lang = ProcessInfo.processInfo.environment["NOTETAKER_LANG"] ?? "hi"
let traceDir = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Logs/NotetakerHelper")

func trace(_ fields: [String: Any]) {
    try? FileManager.default.createDirectory(at: traceDir, withIntermediateDirectories: true)
    var row = fields
    row["ts"] = ISO8601DateFormatter().string(from: Date())
    guard let data = try? JSONSerialization.data(withJSONObject: row),
          let line = String(data: data, encoding: .utf8) else { return }
    let path = traceDir.appendingPathComponent("dictation.jsonl")
    if let handle = try? FileHandle(forWritingTo: path) {
        handle.seekToEndOfFile()
        handle.write(Data((line + "\n").utf8))
        try? handle.close()
    } else {
        try? (line + "\n").write(to: path, atomically: true, encoding: .utf8)
    }
    print(line)
}

// MARK: - Accessibility helpers

func axTrusted() -> Bool {
    AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue(): false] as CFDictionary)
}

func focusedElement() -> AXUIElement? {
    let system = AXUIElementCreateSystemWide()
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute as CFString, &value) == .success,
          let v = value, CFGetTypeID(v) == AXUIElementGetTypeID() else { return nil }
    return (v as! AXUIElement)
}

func axValue(_ element: AXUIElement) -> String? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXValueAttribute as CFString, &value) == .success else { return nil }
    return value as? String
}

func insertViaAX(_ text: String) -> Bool {
    guard let element = focusedElement() else { return false }
    return AXUIElementSetAttributeValue(element, kAXSelectedTextAttribute as CFString, text as CFString) == .success
}

func pasteViaClipboard(_ text: String) -> Bool {
    let pb = NSPasteboard.general
    let saved = pb.pasteboardItems?.compactMap { item -> [NSPasteboard.PasteboardType: Data] in
        var types: [NSPasteboard.PasteboardType: Data] = [:]
        for type in item.types { if let d = item.data(forType: type) { types[type] = d } }
        return types
    } ?? []
    pb.clearContents()
    pb.setString(text, forType: .string)
    let src = CGEventSource(stateID: .combinedSessionState)
    let down = CGEvent(keyboardEventSource: src, virtualKey: CGKeyCode(kVK_ANSI_V), keyDown: true)
    let up = CGEvent(keyboardEventSource: src, virtualKey: CGKeyCode(kVK_ANSI_V), keyDown: false)
    down?.flags = .maskCommand
    up?.flags = .maskCommand
    down?.post(tap: .cghidEventTap)
    up?.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: 0.25)
    let ok = pb.string(forType: .string) == text  // "pasteboard content was not updated" check
    pb.clearContents()
    for item in saved {
        let restore = NSPasteboardItem()
        for (type, data) in item { restore.setData(data, forType: type) }
        pb.writeObjects([restore])
    }
    return ok
}

func insertAndVerify(_ text: String) -> (path: String, verdict: String) {
    let before = focusedElement().flatMap(axValue)
    var path = "ax"
    var ok = insertViaAX(text)
    Thread.sleep(forTimeInterval: 0.15)
    var after = focusedElement().flatMap(axValue)
    var verified = after?.contains(text) ?? false
    // AX set can "succeed" yet insert nothing (web content); verify, then fall back.
    if !verified {
        path = "pasteboard"
        ok = pasteViaClipboard(text)
        Thread.sleep(forTimeInterval: 0.15)
        after = focusedElement().flatMap(axValue)
        verified = after?.contains(text) ?? false
    }
    let verdict = verified ? "verified_before_after" : (ok ? "unverified" : "failed")
    trace(["text": text, "lang": lang, "insert_path": path, "verdict": verdict,
           "before_len": before?.count ?? -1, "after_len": after?.count ?? -1])
    return (path, verdict)
}

// MARK: - Audio capture

final class Recorder {
    private let engine = AVAudioEngine()
    private var samples: [Float] = []
    private let lock = NSLock()
    private(set) var running = false
    private static let levelLock = NSLock()
    private static var _level: Float = 0
    static var level: Float {
        levelLock.lock(); defer { levelLock.unlock() }
        return _level
    }
    private static func publish(_ v: Float) {
        levelLock.lock(); _level = v; levelLock.unlock()
    }

    func start() {
        guard !running else { return }
        trace(["event": "rec_start_begin"])
        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)
        trace(["event": "rec_format", "sr": inFormat.sampleRate, "ch": inFormat.channelCount])
        samples = []
        // Direct resample: AVAudioConverter's per-callback input-block pattern
        // returned 0 frames here; deterministic decimation/interp is simpler.
        input.installTap(onBus: 0, bufferSize: 4096, format: inFormat) { [weak self] buffer, _ in
            guard let self, let ch = buffer.floatChannelData?[0] else { return }
            let n = Int(buffer.frameLength)
            let ratio = inFormat.sampleRate / 16000.0
            var out: [Float] = []
            out.reserveCapacity(Int(Double(n) / ratio) + 1)
            if abs(ratio - 3.0) < 0.01 {
                var i = 0
                while i + 2 < n {
                    out.append((ch[i] + ch[i + 1] + ch[i + 2]) / 3.0)
                    i += 3
                }
            } else {
                let count = Int(Double(n) / ratio)
                for j in 0..<count {
                    let pos = Double(j) * ratio
                    let i0 = Int(pos)
                    guard i0 + 1 < n else { break }
                    let frac = Float(pos - Double(i0))
                    out.append(ch[i0] * (1 - frac) + ch[i0 + 1] * frac)
                }
            }
            let rms = out.isEmpty ? 0 : (out.reduce(0) { $0 + $1 * $1 } / Float(out.count)).squareRoot()
            Recorder.publish(rms)
            self.lock.lock()
            self.samples.append(contentsOf: out)
            self.lock.unlock()
        }
        do { try engine.start(); running = true; trace(["event": "rec_started"]) } catch {
            trace(["event": "audio_start_failed", "error": "\(error)"])
        }
    }

    func stop() -> [Float] {
        guard running else { return [] }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        running = false
        lock.lock()
        let out = samples
        lock.unlock()
        trace(["event": "rec_stop", "samples": out.count])
        return out
    }
}

func wavData(_ samples: [Float]) -> Data {
    var data = Data()
    let n = samples.count
    func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
    func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
    data.append(contentsOf: Array("RIFF".utf8)); u32(UInt32(36 + n * 2))
    data.append(contentsOf: Array("WAVEfmt ".utf8)); u32(16); u16(1); u16(1)
    u32(16000); u32(32000); u16(2); u16(16)
    data.append(contentsOf: Array("data".utf8)); u32(UInt32(n * 2))
    for s in samples {
        let clamped = max(-1.0, min(1.0, s))
        withUnsafeBytes(of: Int16(clamped * 32767).littleEndian) { data.append(contentsOf: $0) }
    }
    return data
}

// MARK: - Local ASR via server

func transcribe(_ wav: Data) -> String? {
    let boundary = "----notetakerspike"
    var body = Data()
    body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n".utf8))
    body.append(wav)
    body.append(Data("\r\n--\(boundary)\r\nContent-Disposition: form-data; name=\"lang\"\r\n\r\n\(lang)\r\n--\(boundary)--\r\n".utf8))
    var request = URLRequest(url: URL(string: serverURL + "/api/quick")!)
    request.httpMethod = "POST"
    request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
    request.httpBody = body
    let sema = DispatchSemaphore(value: 0)
    var text: String?
    URLSession.shared.dataTask(with: request) { data, _, _ in
        if let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            text = obj["text"] as? String
        }
        sema.signal()
    }.resume()
    _ = sema.wait(timeout: .now() + 60)
    return text
}

// Split long recordings at pauses into <= maxSeconds chunks: /api/quick caps at
// 20 s and the model degrades past ~30-45 s in a single pass.
func splitSamples(_ samples: [Float], maxSeconds: Double = 19.0) -> [[Float]] {
    let sr = 16000.0
    let total = Double(samples.count) / sr
    if total <= maxSeconds { return [samples] }
    let frame = 320  // 0.02 s
    let m = samples.count / frame
    var energy = [Float](repeating: 0, count: m)
    for f in 0..<m {
        var sum: Float = 0
        for i in (f * frame)..<((f + 1) * frame) { sum += samples[i] * samples[i] }
        energy[f] = (sum / Float(frame)).squareRoot()
    }
    let thr = max((energy.max() ?? 0) * 0.02, 0.0001)
    var cuts: [Double] = []
    var i = 0
    while i < m {
        if energy[i] < thr {
            var j = i
            while j < m && energy[j] < thr { j += 1 }
            if Double(j - i) * 0.02 >= 0.25 { cuts.append(Double(i + j) / 2 * 0.02) }
            i = j
        } else { i += 1 }
    }
    var pieces: [[Float]] = []
    var start = 0.0
    while total - start > maxSeconds {
        let limit = start + maxSeconds
        let cand = cuts.filter { $0 > start + 1.0 && $0 <= limit }
        let cut = cand.last ?? limit
        pieces.append(Array(samples[Int(start * sr)..<Int(cut * sr)]))
        start = cut
    }
    pieces.append(Array(samples[Int(start * sr)...]))
    return pieces.filter { $0.count >= 4800 }
}

func postHistory(wav: Data, text: String, verdict: String, insertPath: String, asrMs: Int) {
    let boundary = "----notetakerhist"
    var body = Data()
    body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"d.wav\"\r\nContent-Type: audio/wav\r\n\r\n".utf8))
    body.append(wav)
    for (key, value) in [("lang", lang), ("text", text), ("verdict", verdict),
                         ("insert_path", insertPath), ("asr_ms", String(asrMs)),
                         ("source", "dictation")] {
        body.append(Data("\r\n--\(boundary)\r\nContent-Disposition: form-data; name=\"\(key)\"\r\n\r\n\(value)".utf8))
    }
    body.append(Data("\r\n--\(boundary)--\r\n".utf8))
    var request = URLRequest(url: URL(string: serverURL + "/api/history")!)
    request.httpMethod = "POST"
    request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
    request.httpBody = body
    let sema = DispatchSemaphore(value: 0)
    URLSession.shared.dataTask(with: request) { _, _, _ in sema.signal() }.resume()
    _ = sema.wait(timeout: .now() + 15)
}

func dictateOnce(recorder: Recorder) {
    let samples = recorder.stop()
    guard samples.count >= 8000 else {
        trace(["event": "too_short", "samples": samples.count])
        return
    }
    let rms = (samples.reduce(0) { $0 + $1 * $1 } / Float(samples.count)).squareRoot()
    guard rms >= 0.004 else {
        trace(["event": "silence_skipped", "samples": samples.count, "rms": rms])
        return
    }
    let wav = wavData(samples)
    let t0 = Date()
    let chunks = splitSamples(samples)
    let texts = chunks.compactMap { transcribe(wavData($0)) }.filter { !$0.isEmpty }
    let text = texts.joined(separator: " ")
    guard !text.isEmpty else {
        trace(["event": "asr_empty", "samples": samples.count, "chunks": chunks.count])
        DispatchQueue.main.async {
            pillUpdate("no speech recognized")
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { pillUpdate(nil) }
        }
        return
    }
    let asrMs = Int(Date().timeIntervalSince(t0) * 1000)
    let (path, verdict) = insertAndVerify(text)
    trace(["event": "dictation", "asr_ms": asrMs, "insert_path": path, "verdict": verdict, "text": text])
    postHistory(wav: wav, text: text, verdict: verdict, insertPath: path, asrMs: asrMs)
}

// MARK: - Modes

func check() {
    let trusted = axTrusted()
    let front = NSWorkspace.shared.frontmostApplication?.localizedName ?? "?"
    var server = "unreachable"
    let sema = DispatchSemaphore(value: 0)
    URLSession.shared.dataTask(with: URL(string: serverURL + "/api/health")!) { data, _, _ in
        if let data, let s = String(data: data, encoding: .utf8) { server = s }
        sema.signal()
    }.resume()
    _ = sema.wait(timeout: .now() + 5)
    print("accessibility_trusted=\(trusted) frontmost=\(front) server=\(server)")
    if !trusted {
        print("Grant Accessibility to this binary: System Settings > Privacy & Security > Accessibility > add \(CommandLine.arguments[0])")
    }
}

func selftest() {
    let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("notetaker-spike.txt")
    try? "spike baseline\n".write(to: tmp, atomically: true, encoding: .utf8)
    let config = NSWorkspace.OpenConfiguration()
    let sema = DispatchSemaphore(value: 0)
    NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: "/System/Applications/TextEdit.app"),
                                       configuration: config) { _, _ in sema.signal() }
    _ = sema.wait(timeout: .now() + 10)
    NSWorkspace.shared.open(tmp)
    Thread.sleep(forTimeInterval: 1.5)
    let marker = " [notetaker-spike-ok]"
    let (path, verdict) = insertAndVerify(marker)
    print("selftest insert_path=\(path) verdict=\(verdict) (doc left open for inspection: \(tmp.path))")
}

// MARK: - Hold-to-talk hotkey (Carbon: no event tap needed for registration)

let recorder = Recorder()
let nsApp = NSApplication.shared
nsApp.setActivationPolicy(.accessory)

// Menu-bar indicator: idle / listening / processing, always visible.
let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
statusItem.button?.title = "🎙"
let statusMenu = NSMenu()
statusMenu.addItem(NSMenuItem(title: "Hold <3s: push-to-talk · hold ≥3s: latch · press again: stop",
                              action: nil, keyEquivalent: ""))
statusMenu.addItem(.separator())
statusMenu.addItem(NSMenuItem(title: "Quit NotetakerHelper",
                              action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
statusItem.menu = statusMenu
func setStatus(_ emoji: String) { statusItem.button?.title = emoji }

// Floating pill: non-activating panel, visible only while active, live level meter.
final class PillView: NSView {
    var level: Float = 0
    var text: String = ""
    var processing = false
    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds, xRadius: 22, yRadius: 22)
        NSColor.black.withAlphaComponent(0.78).setFill()
        path.fill()
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 13, weight: .medium),
            .foregroundColor: NSColor.white,
        ]
        (text as NSString).draw(at: NSPoint(x: 16, y: 14), withAttributes: attrs)
        let bars = 10
        let x0 = bounds.width - 16 - CGFloat(bars) * 7
        for i in 0..<bars {
            let shape = 0.55 + 0.45 * sin(Double(i) * 1.7 + Date().timeIntervalSinceReferenceDate * 6)
            let h = 4 + CGFloat(min(1.0, level * 6)) * 24 * CGFloat(shape)
            let bar = NSBezierPath(roundedRect: NSRect(x: x0 + CGFloat(i) * 7, y: (bounds.height - h) / 2,
                                                      width: 4, height: h), xRadius: 2, yRadius: 2)
            (processing ? NSColor.systemOrange : NSColor.systemGreen).setFill()
            bar.fill()
        }
    }
}

let pillView = PillView(frame: NSRect(x: 0, y: 0, width: 340, height: 44))
let pillPanel: NSPanel = {
    let p = NSPanel(contentRect: pillView.frame, styleMask: [.borderless, .nonactivatingPanel],
                    backing: .buffered, defer: false)
    p.level = .floating
    p.isFloatingPanel = true
    p.hidesOnDeactivate = false
    p.ignoresMouseEvents = true
    p.backgroundColor = .clear
    p.isOpaque = false
    p.hasShadow = true
    p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
    p.contentView = pillView
    return p
}()
func pillUpdate(_ text: String?, processing: Bool = false) {
    guard let text else {
        pillPanel.orderOut(nil)
        return
    }
    pillView.text = text
    pillView.processing = processing
    if let screen = NSScreen.main {
        let f = screen.visibleFrame
        pillPanel.setFrameOrigin(NSPoint(x: f.midX - 170, y: f.maxY - 70))
    }
    pillPanel.orderFrontRegardless()
}
Timer.scheduledTimer(withTimeInterval: 0.06, repeats: true) { _ in
    guard pillPanel.isVisible else { return }
    pillView.level = max(Recorder.level, pillView.level * 0.8)
    pillView.needsDisplay = true
}

// Persistent floating button: click = latch start, click again = stop + insert.
// Draggable; position persisted. Non-activating so clicks never steal focus.
final class FloatButtonView: NSView {
    var state = "idle" { didSet { needsDisplay = true } }
    var onClick: (() -> Void)?
    private var dragOrigin: NSPoint?
    private var moved = false
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func mouseDown(with event: NSEvent) {
        dragOrigin = event.locationInWindow
        moved = false
    }
    override func mouseDragged(with event: NSEvent) {
        guard let win = window, let start = dragOrigin else { return }
        let cur = event.locationInWindow
        let dx = cur.x - start.x
        let dy = cur.y - start.y
        if abs(dx) > 3 || abs(dy) > 3 { moved = true }
        if moved {
            var o = win.frame.origin
            o.x += dx
            o.y += dy
            win.setFrameOrigin(o)
        }
    }
    override func mouseUp(with event: NSEvent) {
        if moved {
            UserDefaults.standard.set(Double(window?.frame.origin.x ?? 0), forKey: "floatX")
            UserDefaults.standard.set(Double(window?.frame.origin.y ?? 0), forKey: "floatY")
        } else {
            onClick?()
        }
        dragOrigin = nil
    }
    override func draw(_ dirtyRect: NSRect) {
        let circle = NSBezierPath(ovalIn: bounds.insetBy(dx: 2, dy: 2))
        let color: NSColor = state == "idle" ? NSColor.black.withAlphaComponent(0.78)
            : (state == "processing" ? .systemOrange : .systemRed)
        color.setFill()
        circle.fill()
        let glyph = state == "idle" ? "🎙" : (state == "processing" ? "⏳" : "⏹")
        let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 24)]
        let size = (glyph as NSString).size(withAttributes: attrs)
        (glyph as NSString).draw(at: NSPoint(x: (bounds.width - size.width) / 2,
                                            y: (bounds.height - size.height) / 2),
                                 withAttributes: attrs)
    }
}

let floatView = FloatButtonView(frame: NSRect(x: 0, y: 0, width: 56, height: 56))
let floatPanel: NSPanel = {
    let p = NSPanel(contentRect: floatView.frame, styleMask: [.borderless, .nonactivatingPanel],
                    backing: .buffered, defer: false)
    p.level = .floating
    p.isFloatingPanel = true
    p.hidesOnDeactivate = false
    p.backgroundColor = .clear
    p.isOpaque = false
    p.hasShadow = true
    p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
    p.contentView = floatView
    p.ignoresMouseEvents = false
    return p
}()
floatView.onClick = {
    if dictationState == "idle" {
        recorder.start()
        dictationState = "latched"
        setStatus("🔴")
        pillUpdate("latched — click or hotkey to stop")
        floatView.state = "latched"
        trace(["event": "float_start"])
        print("latched via floating button; click again or press hotkey to stop")
    } else if dictationState == "latched" {
        trace(["event": "float_stop"])
        finalizeDictation()
    }
}
let floatX = UserDefaults.standard.object(forKey: "floatX") as? Double
    ?? Double((NSScreen.main?.visibleFrame.maxX ?? 1200) - 90)
let floatY = UserDefaults.standard.object(forKey: "floatY") as? Double
    ?? Double((NSScreen.main?.visibleFrame.minY ?? 0) + 120)
floatPanel.setFrameOrigin(NSPoint(x: floatX, y: floatY))
floatPanel.orderFrontRegardless()

// Dictation state machine: idle -> holding -> (latched | processing) -> idle.
var dictationState = "idle"
var pressStart = Date()
let latchSeconds = Double(ProcessInfo.processInfo.environment["NOTETAKER_LATCH_SECONDS"] ?? "3") ?? 3.0
func finalizeDictation() {
    dictationState = "processing"
    setStatus("⏳")
    pillUpdate("transcribing…", processing: true)
    floatView.state = "processing"
    DispatchQueue.global().async {
        dictateOnce(recorder: recorder)
        DispatchQueue.main.async {
            dictationState = "idle"
            setStatus("🎙")
            pillUpdate(nil)
            floatView.state = "idle"
        }
    }
}

var hotKeyRef: EventHotKeyRef?
let hotKeyID = EventHotKeyID(signature: OSType(0x4E544B52), id: 1)  // "NTKR"
var specs = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
             EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))]
InstallEventHandler(GetApplicationEventTarget(), { _, event, _ -> OSStatus in
    guard let event else { return noErr }
    let kind = GetEventKind(event)
    trace(["event": "hotkey", "kind": kind == UInt32(kEventHotKeyPressed) ? "pressed" : "released",
           "state": dictationState])
    if kind == UInt32(kEventHotKeyPressed) {
        if dictationState == "latched" {
            finalizeDictation()
        } else if dictationState == "idle" {
            recorder.start()
            pressStart = Date()
            dictationState = "holding"
            setStatus("🔴")
            pillUpdate("listening… release to insert")
            floatView.state = "holding"
            print("recording… release to dictate, or keep holding ≥3s to latch")
        }
    } else if kind == UInt32(kEventHotKeyReleased) {
        if dictationState == "holding" {
            let held = Date().timeIntervalSince(pressStart)
            if held >= latchSeconds {
                dictationState = "latched"
                trace(["event": "latched", "held_s": held])
                pillUpdate("latched — press hotkey to stop")
                floatView.state = "latched"
                print("latched: keep speaking; press the hotkey again to stop and insert")
            } else {
                finalizeDictation()
            }
        }
    }
    return noErr
}, 2, &specs, nil, nil)
let hotkeyChoice = ProcessInfo.processInfo.environment["NOTETAKER_HOTKEY"] ?? "option-space"
let (hkCode, hkMods): (UInt32, UInt32) = switch hotkeyChoice {
case "option-d": (UInt32(kVK_ANSI_D), UInt32(optionKey))
case "ctrl-option-space": (UInt32(kVK_Space), UInt32(controlKey | optionKey))
default: (UInt32(kVK_Space), UInt32(optionKey))
}
let regStatus = RegisterEventHotKey(hkCode, hkMods, hotKeyID, GetApplicationEventTarget(), 0, &hotKeyRef)
trace(["event": "hotkey_register", "choice": hotkeyChoice, "status": regStatus, "ref_nil": hotKeyRef == nil])

let args = CommandLine.arguments
if args.contains("--check") { check(); exit(0) }
if args.contains("--selftest") { selftest(); exit(0) }
if args.contains("--press") {
    // Self-test of event dispatch: post the hotkey chord to ourselves.
    DispatchQueue.global().async {
        Thread.sleep(forTimeInterval: 0.5)
        let src = CGEventSource(stateID: .combinedSessionState)
        let down = CGEvent(keyboardEventSource: src, virtualKey: CGKeyCode(kVK_Space), keyDown: true)
        let up = CGEvent(keyboardEventSource: src, virtualKey: CGKeyCode(kVK_Space), keyDown: false)
        down?.flags = .maskAlternate
        up?.flags = .maskAlternate
        down?.post(tap: .cghidEventTap)
        Thread.sleep(forTimeInterval: 1.2)  // < latch threshold: push-to-talk path
        up?.post(tap: .cghidEventTap)
        Thread.sleep(forTimeInterval: 2.0)
        exit(0)
    }
}
if !axTrusted() {
    print("Accessibility not trusted; run --check for instructions. Hotkey registered but insertion will fail safely.")
}
if !args.contains("--check") && !args.contains("--selftest") {
    let micSema = DispatchSemaphore(value: 0)
    AVCaptureDevice.requestAccess(for: .audio) { granted in
        trace(["event": "mic_permission", "granted": granted])
        micSema.signal()
    }
    _ = micSema.wait(timeout: .now() + 60)
}
print("NotetakerHelper running: hold <3s = push-to-talk, hold ≥3s = latch, press again = stop (lang=\(lang), server=\(serverURL)).")
// NSApplication's run loop integrates the Carbon event dispatcher.
nsApp.run()
