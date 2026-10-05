import AppKit
import SwiftUI

/// Notion-style floating card in the top-right corner: "Teams call detected — Start notes?", then a
/// recording pill with a timer and Stop, then "Making notes…". Doesn't depend on macOS notifications
/// and stays reachable even when the menu bar icon is hidden behind the notch.
@MainActor
final class FloatingPanel {
    private let state: AppState
    private var panel: NSPanel?
    private var hosting: NSHostingView<FloatingView>?

    init(state: AppState) { self.state = state }

    func update(visible: Bool) {
        guard visible else { panel?.orderOut(nil); return }
        if panel == nil { create() }
        // Let SwiftUI lay out the new content first, then size and pin to the top-right corner.
        DispatchQueue.main.async { [weak self] in self?.place() }
        panel?.orderFrontRegardless()
    }

    private func create() {
        let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 360, height: 80),
                        styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
        p.level = .statusBar
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.isMovableByWindowBackground = true
        p.becomesKeyOnlyIfNeeded = true
        p.hidesOnDeactivate = false
        // Keep the card out of screen shares / recordings (Teams, Zoom, screenshots).
        p.sharingType = .none
        let view = NSHostingView(rootView: FloatingView(state: state))
        p.contentView = view
        hosting = view
        panel = p
    }

    private func place() {
        guard let panel, let hosting else { return }
        let size = hosting.fittingSize
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let area = screen.visibleFrame
        panel.setFrame(NSRect(x: area.maxX - size.width - 14, y: area.maxY - size.height - 10,
                              width: size.width, height: size.height), display: true)
    }
}

struct FloatingView: View {
    @ObservedObject var state: AppState

    var body: some View {
        content
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(VisualEffect().clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous)))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(.white.opacity(0.12)))
            .padding(8)  // room for the shadow
            .fixedSize()
    }

    @ViewBuilder private var content: some View {
        switch state.phase {
        case .recording: recordingPill
        case .processing(let status): processing(status)
        default:
            if let app = state.detectedApp { prompt(app) }
        }
    }

    private func prompt(_ app: String) -> some View {
        HStack(spacing: 14) {
            Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 42, height: 42)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(app) call detected").font(.system(size: 14, weight: .semibold))
                Text("Take notes for this meeting?").font(.system(size: 12)).foregroundStyle(.secondary)
            }
            Spacer(minLength: 12)
            Button("Not now") { state.promptDismissed = true }
                .buttonStyle(.bordered).controlSize(.large)
            Button("Start notes") { state.start() }
                .buttonStyle(.borderedProminent).tint(Color(red: 0.36, green: 0.30, blue: 0.94)).controlSize(.large)
        }
        .frame(width: 400)
    }

    private var recordingPill: some View {
        HStack(spacing: 10) {
            PulsingDot()
            Text("Recording").font(.system(size: 13, weight: .semibold))
            Text(state.elapsed).font(.system(size: 13).monospacedDigit()).foregroundStyle(.secondary)
            if let app = state.detectedApp {
                Text("· \(app)").font(.system(size: 12)).foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            Button("Stop") { state.stop(mode: "claude") }
                .buttonStyle(.borderedProminent).tint(.red).controlSize(.regular)
            Button { state.pillHidden = true } label: { Image(systemName: "xmark").font(.system(size: 10, weight: .bold)) }
                .buttonStyle(.plain).foregroundStyle(.secondary).help("Hide (keeps recording)")
        }
    }

    private func processing(_ status: String) -> some View {
        HStack(spacing: 10) {
            ProgressView().controlSize(.small)
            VStack(alignment: .leading, spacing: 1) {
                Text("Making notes…").font(.system(size: 13, weight: .semibold))
                Text(status).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
            }
        }
        .frame(minWidth: 220, alignment: .leading)
    }
}

/// PhaseAnimator instead of @State: @State is a macro in the macOS 26+ SDK, and Command Line Tools
/// don't ship the SwiftUIMacros plugin (only Xcode does).
struct PulsingDot: View {
    var body: some View {
        PhaseAnimator([1.0, 0.35]) { opacity in
            Circle().fill(.red).frame(width: 10, height: 10).opacity(opacity)
        } animation: { _ in .easeInOut(duration: 0.9) }
    }
}

struct VisualEffect: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = .popover
        v.blendingMode = .behindWindow
        v.state = .active
        return v
    }
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}
