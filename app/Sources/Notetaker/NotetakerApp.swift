import AppKit
import ServiceManagement
import SwiftUI

@main
struct NotetakerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var state = AppState.shared

    var body: some Scene {
        MenuBarExtra {
            MenuContent(state: state)
        } label: {
            switch state.phase {
            case .idle: Image(systemName: "waveform")
            case .recording: HStack(spacing: 3) { Image(systemName: "record.circle"); Text(state.elapsed) }
            case .processing: Image(systemName: "hourglass")
            case .failed: Image(systemName: "exclamationmark.triangle")
            }
        }
    }
}

/// URL control so Claude, Shortcuts or Raycast can drive recording:
///   open notetaker://start · notetaker://stop?mode=claude|local · notetaker://discard
final class AppDelegate: NSObject, NSApplicationDelegate {
    func application(_ application: NSApplication, open urls: [URL]) {
        Task { @MainActor in
            for url in urls { AppState.shared.handle(url) }
        }
    }
}

@MainActor
final class AppState: ObservableObject {
    static let shared = AppState()

    enum Phase: Equatable { case idle, recording(Date), processing(String), failed(String) }

    @Published var phase: Phase = .idle
    @Published var elapsed = "0:00"
    @Published var recent: [URL] = Pipeline.recentNotes()
    @Published var launchAtLogin = SMAppService.mainApp.status == .enabled

    private let recorder = Recorder()
    private var timer: Timer?
    private var lastSession: URL?

    init() {
        recorder.onError = { [weak self] error in
            Task { @MainActor in self?.fail("Recording error: \(error.localizedDescription)") }
        }
    }

    func handle(_ url: URL) {
        let mode = URLComponents(url: url, resolvingAgainstBaseURL: false)?
            .queryItems?.first { $0.name == "mode" }?.value ?? "claude"
        switch (url.host, phase) {
        case ("start", .idle), ("start", .failed): start()
        case ("stop", .recording): stop(mode: mode == "local" ? "local" : "claude")
        case ("discard", .recording): discard()
        default: break
        }
    }

    func start() {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd HHmm"
        let dir = Pipeline.notesDir.appendingPathComponent(fmt.string(from: Date()))
        Task {
            do {
                try await recorder.start(in: dir)
                let started = Date()
                phase = .recording(started)
                elapsed = "0:00"
                timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
                    Task { @MainActor in self?.tick(started) }
                }
            } catch {
                fail(error.localizedDescription)
            }
        }
    }

    private func tick(_ started: Date) {
        let s = Int(Date().timeIntervalSince(started))
        elapsed = s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
                            : String(format: "%d:%02d", s / 60, s % 60)
    }

    func stop(mode: String) {
        timer?.invalidate()
        Task {
            guard let session = await recorder.stop() else { return phase = .idle }
            lastSession = session
            run(session: session, mode: mode)
        }
    }

    func discard() {
        timer?.invalidate()
        Task {
            if let session = await recorder.stop() { try? FileManager.default.removeItem(at: session) }
            phase = .idle
        }
    }

    func retry(mode: String) {
        if let lastSession { run(session: lastSession, mode: mode) }
    }

    private func run(session: URL, mode: String) {
        phase = .processing("Starting…")
        Task {
            do {
                let (notes, finished) = try await Pipeline.process(session: session, mode: mode) { status in
                    Task { @MainActor in self.phase = .processing(status) }
                }
                lastSession = notes.deletingLastPathComponent()
                phase = .idle
                recent = Pipeline.recentNotes()
                // Pending = Claude Desktop's scheduled task will add the summary (and notify).
                if finished { NSWorkspace.shared.open(notes) }
            } catch {
                fail(error.localizedDescription)
            }
        }
    }

    private func fail(_ message: String) {
        timer?.invalidate()
        phase = .failed(message)
    }

    var canRetry: Bool { lastSession != nil }

    func dismissError() { phase = .idle }

    func toggleLaunchAtLogin() {
        do {
            if launchAtLogin { try SMAppService.mainApp.unregister() } else { try SMAppService.mainApp.register() }
        } catch {
            fail("Launch at login: \(error.localizedDescription)")
        }
        launchAtLogin = SMAppService.mainApp.status == .enabled
    }

    func openContext() {
        let url = Pipeline.contextFile
        if !FileManager.default.fileExists(atPath: url.path) {
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? """
            # Context for meeting summaries
            Who you are, your team, projects and names that come up often.
            Claude and the local model read this before summarizing.

            Example: I'm a product manager on the payments team. Projects: Checkout v2, Mobile app. People: Anna (QA), Pēteris (backend).

            """.write(to: url, atomically: true, encoding: .utf8)
        }
        NSWorkspace.shared.open(url)
    }
}

struct MenuContent: View {
    @ObservedObject var state: AppState

    var body: some View {
        switch state.phase {
        case .idle:
            Button("Start Recording") { state.start() }
        case .recording:
            Text("Recording — \(state.elapsed)")
            Button("Stop & Summarize with Claude") { state.stop(mode: "claude") }
            Button("Stop & Summarize Locally (private)") { state.stop(mode: "local") }
            Button("Discard Recording") { state.discard() }
        case .processing(let status):
            Text(status)
        case .failed(let message):
            Text(message).lineLimit(3)
            if state.canRetry {
                Button("Retry with Claude") { state.retry(mode: "claude") }
                Button("Retry Locally") { state.retry(mode: "local") }
            }
            Button("Dismiss") { state.dismissError() }
        }

        Divider()
        if !state.recent.isEmpty {
            Menu("Recent Notes") {
                ForEach(state.recent, id: \.self) { url in
                    Button(url.deletingLastPathComponent().lastPathComponent) { NSWorkspace.shared.open(url) }
                }
            }
        }
        Button("Open Notes Folder") {
            try? FileManager.default.createDirectory(at: Pipeline.notesDir, withIntermediateDirectories: true)
            NSWorkspace.shared.open(Pipeline.notesDir)
        }
        Button("Edit Context & Names…") { state.openContext() }
        Divider()
        Toggle("Launch at Login", isOn: Binding(get: { state.launchAtLogin }, set: { _ in state.toggleLaunchAtLogin() }))
        Button("Quit Notetaker") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }
}
