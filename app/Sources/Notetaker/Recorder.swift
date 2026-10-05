import AVFoundation
import ScreenCaptureKit

/// Records all system audio (every app) and the microphone into two separate WAV files
/// using ScreenCaptureKit. Separate tracks give us "Me" vs "Them" for free.
final class Recorder: NSObject, SCStreamOutput, SCStreamDelegate {
    private var stream: SCStream?
    private let queue = DispatchQueue(label: "notetaker.audio")
    private var tracks: [SCStreamOutputType: TrackWriter] = [:]
    private var startTime = CMTime.zero
    private var startDate = Date()
    private(set) var sessionDir: URL?
    var onError: ((Error) -> Void)?

    func start(in dir: URL) async throws {
        guard await AVCaptureDevice.requestAccess(for: .audio) else {
            throw NSError(domain: "Notetaker", code: 1, userInfo: [NSLocalizedDescriptionKey:
                "Microphone access denied — enable Notetaker in System Settings › Privacy & Security › Microphone"])
        }
        // Throws if Screen & System Audio Recording permission is missing (macOS shows the prompt).
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else {
            throw NSError(domain: "Notetaker", code: 2, userInfo: [NSLocalizedDescriptionKey: "No display found"])
        }
        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])

        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 48000
        config.channelCount = 1
        config.captureMicrophone = true
        // We only want audio; keep the (mandatory) video stream as cheap as possible.
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.showsCursor = false

        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        sessionDir = dir
        tracks = [
            .audio: TrackWriter(url: dir.appendingPathComponent("system.wav")),
            .microphone: TrackWriter(url: dir.appendingPathComponent("mic.wav")),
        ]
        startTime = CMClockGetTime(CMClockGetHostTimeClock())
        startDate = Date()

        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        try stream.addStreamOutput(self, type: .microphone, sampleHandlerQueue: queue)
        try await stream.startCapture()
        self.stream = stream
    }

    /// Stops capture, closes files and writes meta.json. Returns the session folder.
    func stop() async -> URL? {
        if let stream { try? await stream.stopCapture() }
        stream = nil
        guard let dir = sessionDir else { return nil }
        let start = startTime
        let meta: [String: Any] = queue.sync {
            var trackMeta: [String: Any] = [:]
            for (type, writer) in tracks {
                writer.close()
                guard writer.framesWritten > 0 else { continue }
                trackMeta[type == .audio ? "system" : "mic"] = [
                    "file": writer.url.lastPathComponent,
                    "offset": max(0, CMTimeGetSeconds(CMTimeSubtract(writer.firstPTS, start))),
                ]
            }
            tracks = [:]
            return [
                "started": ISO8601DateFormatter().string(from: startDate),
                "tracks": trackMeta,
            ]
        }
        if let data = try? JSONSerialization.data(withJSONObject: meta, options: .prettyPrinted) {
            try? data.write(to: dir.appendingPathComponent("meta.json"))
        }
        sessionDir = nil
        return dir
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type != .screen, sb.isValid, let writer = tracks[type] else { return }
        do { try writer.append(sb) } catch { onError?(error) }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        onError?(error)
    }
}

/// Writes one audio track, inserting silence for gaps so timestamps stay aligned.
final class TrackWriter {
    let url: URL
    private var file: AVAudioFile?
    private(set) var firstPTS = CMTime.invalid
    private(set) var framesWritten: AVAudioFramePosition = 0

    init(url: URL) { self.url = url }

    func append(_ sb: CMSampleBuffer) throws {
        guard let buffer = Self.pcmBuffer(from: sb) else { return }
        let format = buffer.format
        let pts = CMSampleBufferGetPresentationTimeStamp(sb)
        if file == nil {
            let settings: [String: Any] = [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: format.sampleRate,
                AVNumberOfChannelsKey: format.channelCount,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
                AVLinearPCMIsNonInterleaved: false,
            ]
            file = try AVAudioFile(forWriting: url, settings: settings,
                                   commonFormat: format.commonFormat, interleaved: format.isInterleaved)
            firstPTS = pts
        }
        guard let file else { return }

        // Fill gaps (e.g. nothing playing) with silence so both tracks share one timeline.
        let expected = AVAudioFramePosition(CMTimeGetSeconds(CMTimeSubtract(pts, firstPTS)) * format.sampleRate)
        let gap = expected - framesWritten
        if gap > AVAudioFramePosition(format.sampleRate * 0.1),
           let silence = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(gap)) {
            silence.frameLength = AVAudioFrameCount(gap)  // buffers are zero-initialised
            try file.write(from: silence)
            framesWritten += gap
        }
        try file.write(from: buffer)
        framesWritten += AVAudioFramePosition(buffer.frameLength)
    }

    func close() { file = nil }

    static func pcmBuffer(from sb: CMSampleBuffer) -> AVAudioPCMBuffer? {
        guard let desc = CMSampleBufferGetFormatDescription(sb),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc),
              let format = AVAudioFormat(streamDescription: asbd) else { return nil }
        let frames = AVAudioFrameCount(CMSampleBufferGetNumSamples(sb))
        guard frames > 0, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else { return nil }
        buffer.frameLength = frames
        let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(
            sb, at: 0, frameCount: Int32(frames), into: buffer.mutableAudioBufferList)
        return status == noErr ? buffer : nil
    }
}
