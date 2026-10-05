import AppKit
import CoreAudio

/// Detects calls by watching which processes are using the microphone (Core Audio process objects,
/// macOS 14.2+). Needs no extra permission. A known call app holding the mic for a few seconds = meeting
/// started; no call app on the mic for a minute = meeting ended.
@MainActor
final class MeetingDetector {
    var onMeetingStarted: ((String) -> Void)?
    var onMeetingEnded: (() -> Void)?
    /// The call moved to another app (e.g. Teams → Slack huddle) without the mic going quiet.
    var onAppChanged: ((String) -> Void)?

    private(set) var inCall = false
    private(set) var currentApp: String?
    private var activeSince: Date?
    private var lastSeen: Date?
    private var timer: Timer?
    /// When each call app started holding the mic; the newest one is "the" meeting app.
    private var firstSeen: [String: Date] = [:]

    static let startAfter: TimeInterval = 8   // ignore brief mic use (dictation, Siri, a quick voice note)
    static let endAfter: TimeInterval = 60    // tolerate apps that release the mic while muted

    /// Bundle-ID prefixes of apps whose microphone use means "a call". Browsers count because the mic
    /// in a browser is almost always Meet/Teams-web/Zoom-web.
    static let callApps: [(prefix: String, name: String)] = [
        ("com.microsoft.teams", "Teams"), ("us.zoom.", "Zoom"), ("com.tinyspeck.slackmacgap", "Slack"),
        ("com.cisco.webex", "Webex"), ("com.webex.", "Webex"), ("com.apple.FaceTime", "FaceTime"),
        ("com.google.Chrome", "Chrome"), ("com.apple.Safari", "Safari"), ("com.apple.WebKit", "Safari"),
        ("company.thebrowser.", "Arc"), ("org.mozilla.firefox", "Firefox"), ("com.microsoft.edgemac", "Edge"),
        ("com.brave.Browser", "Brave"), ("com.hnc.Discord", "Discord"), ("net.whatsapp.", "WhatsApp"),
        ("desktop.WhatsApp", "WhatsApp"), ("ru.keepcoder.Telegram", "Telegram"),
    ]

    func start() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        inCall = false
        currentApp = nil
        activeSince = nil
        firstSeen = [:]
    }

    private func tick() {
        let now = Date()
        let present = Set(AudioProcesses.inputBundleIDs().compactMap(Self.callAppName))
        firstSeen = firstSeen.filter { present.contains($0.key) }
        for name in present where firstSeen[name] == nil { firstSeen[name] = now }
        let app = firstSeen.max { $0.value < $1.value }?.key
        if let app {
            lastSeen = now
            if inCall, app != currentApp { onAppChanged?(app) }
            currentApp = app
            if activeSince == nil { activeSince = now }
            if !inCall, let since = activeSince, now.timeIntervalSince(since) >= Self.startAfter {
                inCall = true
                onMeetingStarted?(app)
            }
        } else {
            activeSince = nil  // a meeting needs continuous mic use to start
            if inCall, let lastSeen, now.timeIntervalSince(lastSeen) >= Self.endAfter {
                inCall = false
                currentApp = nil
                onMeetingEnded?()
            } else if !inCall {
                currentApp = nil
            }
        }
    }

    static func callAppName(_ bundleID: String) -> String? {
        callApps.first { bundleID.hasPrefix($0.prefix) }?.name
    }
}

/// Reads Core Audio's per-process objects to find who is currently capturing audio input.
enum AudioProcesses {
    static func inputBundleIDs() -> [String] {
        var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyProcessObjectList,
                                              mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        let system = AudioObjectID(kAudioObjectSystemObject)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(system, &addr, 0, nil, &size) == noErr, size > 0 else { return [] }
        var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(system, &addr, 0, nil, &size, &ids) == noErr else { return [] }

        return ids.compactMap { id in
            guard uint32(id, kAudioProcessPropertyIsRunningInput) == 1 else { return nil }
            if let bid = string(id, kAudioProcessPropertyBundleID), !bid.isEmpty { return bid }
            // Some helpers report no bundle ID; fall back to the owning app of the PID.
            let pid = pid_t(bitPattern: uint32(id, kAudioProcessPropertyPID) ?? 0)
            return NSRunningApplication(processIdentifier: pid)?.bundleIdentifier
        }
    }

    private static func uint32(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector) -> UInt32? {
        var addr = AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var value: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        return AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &value) == noErr ? value : nil
    }

    private static func string(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
        var addr = AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var ref: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        let status = withUnsafeMutablePointer(to: &ref) { AudioObjectGetPropertyData(id, &addr, 0, nil, &size, $0) }
        guard status == noErr, let ref else { return nil }
        return ref.takeRetainedValue() as String
    }
}
