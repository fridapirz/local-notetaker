import Foundation

/// Runs the Python pipeline (`notetaker process <dir>`) through uv and streams STATUS lines back.
enum Pipeline {
    static let home = FileManager.default.homeDirectoryForCurrentUser

    static var notesDir: URL {
        let configURL = home.appendingPathComponent(".config/notetaker/config.json")
        if let data = try? Data(contentsOf: configURL),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let dir = json["notes_dir"] as? String {
            return URL(fileURLWithPath: (dir as NSString).expandingTildeInPath)
        }
        return home.appendingPathComponent("Notes/meetings")
    }

    static var contextFile: URL { home.appendingPathComponent(".config/notetaker/context.md") }
    static var configFile: URL { home.appendingPathComponent(".config/notetaker/config.json") }

    /// Pipeline sources: bundled in the .app, or overridden for development.
    static var pipelineDir: URL? {
        if let env = ProcessInfo.processInfo.environment["NOTETAKER_PIPELINE"] {
            return URL(fileURLWithPath: env)
        }
        return Bundle.main.resourceURL?.appendingPathComponent("pipeline")
    }

    static var uvPath: String? {
        [Bundle.main.resourceURL?.appendingPathComponent("bin/uv").path ?? "", "\(home.path)/.local/bin/uv", "/opt/homebrew/bin/uv", "/usr/local/bin/uv", "\(home.path)/.cargo/bin/uv"]
            .first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    static func venvDir() -> URL {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return support.appendingPathComponent("Notetaker/venv")
    }

    /// Returns notes.md and whether the summary is done (false = queued for Claude Desktop).
    static func process(session: URL, mode: String, onStatus: @escaping @Sendable (String) -> Void) async throws -> (URL, Bool) {
        guard let uv = uvPath else {
            throw err("uv not found — install with: curl -LsSf https://astral.sh/uv/install.sh | sh")
        }
        guard let project = pipelineDir else { throw err("pipeline sources missing from app bundle") }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: uv)
        proc.arguments = ["run", "--quiet", "--frozen", "--project", project.path, "--python", "3.12",
                          "notetaker", "process", session.path, "--mode", mode]
        proc.environment = environment()

        let out = Pipe()
        proc.standardOutput = out
        let logURL = session.appendingPathComponent("pipeline.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        proc.standardError = try FileHandle(forWritingTo: logURL)

        // Read stdout sequentially on a background thread, then wait for exit: no handler races.
        return try await Task.detached {
            try proc.run()
            var done: URL?
            var finished = true
            var failure: String?
            var buffer = Data()
            let reader = out.fileHandleForReading
            func handle(_ line: String) {
                if line.hasPrefix("STATUS: ") { onStatus(String(line.dropFirst(8))) }
                else if line.hasPrefix("DONE: ") { done = URL(fileURLWithPath: String(line.dropFirst(6))) }
                else if line.hasPrefix("PENDING: ") {
                    done = URL(fileURLWithPath: String(line.dropFirst(9)))
                    finished = false
                }
                else if line.hasPrefix("ERROR: ") { failure = String(line.dropFirst(7)) }
            }
            while true {
                let data = reader.availableData
                if data.isEmpty { break }
                buffer.append(data)
                while let nl = buffer.firstIndex(of: 0x0A) {
                    handle(String(decoding: buffer[..<nl], as: UTF8.self))
                    buffer.removeSubrange(...nl)
                }
            }
            proc.waitUntilExit()
            if let done, proc.terminationStatus == 0 { return (done, finished) }
            throw err(failure ?? "pipeline exited \(proc.terminationStatus) — see \(logURL.path)")
        }.value
    }

    static func environment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "\(home.path)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + (env["PATH"] ?? "")
        env["UV_PROJECT_ENVIRONMENT"] = venvDir().path
        env["PYTHONUNBUFFERED"] = "1"
        env["TOKENIZERS_PARALLELISM"] = "false"
        return env
    }

    // MARK: Meetings page server (`notetaker serve`): index with tickable action items, 127.0.0.1 only.

    static var serverPort: Int {
        guard let data = try? Data(contentsOf: configFile),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let port = json["server_port"] as? Int else { return 47821 }
        return port
    }

    static var meetingsPage: URL { URL(string: "http://127.0.0.1:\(serverPort)/")! }

    nonisolated(unsafe) private static var server: Process?

    /// Started at launch, stopped at quit (the server also exits on its own if the app goes away).
    static func startServer() {
        guard server?.isRunning != true, let uv = uvPath, let project = pipelineDir else { return }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: uv)
        proc.arguments = ["run", "--quiet", "--project", project.path, "--python", "3.12", "notetaker", "serve",
                          "--app-pid", String(ProcessInfo.processInfo.processIdentifier)]
        proc.environment = environment()
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        try? proc.run()
        server = proc
    }

    static func stopServer() {
        server?.terminate()
    }

    static func recentNotes(limit: Int = 8) -> [URL] {
        let fm = FileManager.default
        guard let dirs = try? fm.contentsOfDirectory(at: notesDir, includingPropertiesForKeys: nil) else { return [] }
        return dirs.map { $0.appendingPathComponent("notes.md") }
            .filter { fm.fileExists(atPath: $0.path) }
            .sorted { $0.deletingLastPathComponent().lastPathComponent > $1.deletingLastPathComponent().lastPathComponent }
            .prefix(limit).map { $0 }
    }

    /// The human-friendly page for a meeting: served (sidebar + tickable action items) while the server runs,
    /// else notes.html next to notes.md, falling back to the Markdown.
    static func readable(_ notesMD: URL) -> URL {
        let folder = notesMD.deletingLastPathComponent().lastPathComponent
        if server?.isRunning == true,
           let name = folder.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))),
           let url = URL(string: "\(meetingsPage.absoluteString)\(name)/notes.html") {
            return url
        }
        let page = notesMD.deletingLastPathComponent().appendingPathComponent("notes.html")
        return FileManager.default.fileExists(atPath: page.path) ? page : notesMD
    }

    static func err(_ msg: String) -> NSError {
        NSError(domain: "Notetaker", code: 10, userInfo: [NSLocalizedDescriptionKey: msg])
    }
}
