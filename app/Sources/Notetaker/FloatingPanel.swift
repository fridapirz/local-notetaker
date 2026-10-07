import AppKit
import SwiftUI

/// Notion-style floating card in the top-right corner: "Teams call detected — Start notes?", then a
/// recording pill with a timer and Stop, then "Making notes…". Doesn't depend on macOS notifications
/// and stays reachable even when the menu bar icon is hidden behind the notch. Drag it anywhere; it stays
/// there for the rest of that meeting (prompt → recording → notes), and the next one starts in the corner.
@MainActor
final class FloatingPanel {
    private let state: AppState
    private var panel: CardPanel?
    private var hosting: NSHostingView<FloatingView>?
    /// Where the card was dragged to during the current meeting; nil means the corner.
    private var draggedFrame: NSRect?

    init(state: AppState) { self.state = state }

    func update(visible: Bool) {
        guard visible else {
            panel?.orderOut(nil)
            panel?.isDragging = false  // a hidden card gets no mouse-up
            return
        }
        if panel == nil { create() }
        // Let SwiftUI lay out the new content first, then size and pin to the corner (or where it was dragged).
        DispatchQueue.main.async { [weak self] in self?.place() }
        panel?.orderFrontRegardless()
    }

    /// AppState calls this when a meeting is over (notes done, recording discarded, prompt declined or gone).
    func resetPosition() { draggedFrame = nil }

    private func create() {
        let p = CardPanel(contentRect: NSRect(x: 0, y: 0, width: 360, height: 80),
                        styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
        p.level = .statusBar
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.becomesKeyOnlyIfNeeded = true
        p.hidesOnDeactivate = false
        // Keep the card out of screen shares / recordings (Teams, Zoom, screenshots).
        p.sharingType = .none
        p.onDragEnd = { [weak self] in self?.dragEnded() }
        let view = NSHostingView(rootView: FloatingView(state: state))
        p.contentView = view
        hosting = view
        panel = p
    }

    private func dragEnded() {
        guard let panel else { return }
        draggedFrame = panel.frame
        place()  // pull it back on screen if it was dropped past an edge, and apply any resize skipped mid-drag
    }

    private func place() {
        guard let panel, let hosting, !panel.isDragging else { return }
        let size = hosting.fittingSize
        let draggedScreen = draggedFrame.flatMap { f in
            NSScreen.screens.first { $0.frame.contains(NSPoint(x: f.midX, y: f.midY)) }
        }
        guard let screen = draggedScreen ?? NSScreen.main ?? NSScreen.screens.first else { return }
        let area = screen.visibleFrame
        var frame: NSRect
        if let saved = draggedFrame {
            // The card's width changes between prompt, pill and "Making notes…": keep its top edge and the
            // side nearer the screen edge where it was left, and keep it on a connected screen.
            frame = NSRect(x: saved.midX < area.midX ? saved.minX : saved.maxX - size.width,
                           y: saved.maxY - size.height, width: size.width, height: size.height)
            frame.origin.x = min(max(frame.minX, area.minX), area.maxX - size.width)
            frame.origin.y = min(max(frame.minY, area.minY), area.maxY - size.height)
        } else {
            frame = NSRect(x: area.maxX - size.width - 14, y: area.maxY - size.height - 10,
                           width: size.width, height: size.height)
        }
        panel.setFrame(frame, display: true)
    }
}

final class CardPanel: NSPanel {
    /// True while CardBackground is dragging the card; place() leaves it alone meanwhile.
    var isDragging = false
    var onDragEnd: (() -> Void)?
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
            Button("Not now") { state.declinePrompt() }
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

/// The card's background, which is also its drag handle. isMovableByWindowBackground doesn't move this
/// SwiftUI-hosted borderless panel, so track the drag here; the mouse-up comes back to this view too,
/// rather than landing on whichever button ends up under the cursor.
final class CardBackground: NSVisualEffectView {
    private var dragStart: (mouse: NSPoint, origin: NSPoint)?

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func mouseDown(with event: NSEvent) {
        if let window { dragStart = (NSEvent.mouseLocation, window.frame.origin) }
    }

    override func mouseDragged(with event: NSEvent) {
        guard let panel = window as? CardPanel, let dragStart else { return }
        panel.isDragging = true
        let mouse = NSEvent.mouseLocation  // screen coordinates, so moving the window doesn't skew them
        panel.setFrameOrigin(NSPoint(x: dragStart.origin.x + mouse.x - dragStart.mouse.x,
                                     y: dragStart.origin.y + mouse.y - dragStart.mouse.y))
    }

    override func mouseUp(with event: NSEvent) {
        dragStart = nil
        guard let panel = window as? CardPanel, panel.isDragging else { return }  // a plain click isn't a move
        panel.isDragging = false
        panel.onDragEnd?()
    }
}

struct VisualEffect: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = CardBackground()
        v.material = .popover
        v.blendingMode = .behindWindow
        v.state = .active
        return v
    }
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}
