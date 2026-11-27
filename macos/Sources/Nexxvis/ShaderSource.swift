import Foundation

enum ShaderSource {
    /// Looks in the app bundle first, then next to the source tree so
    /// `swift run Nexxvis --snapshot` works without a bundled app.
    static func load() throws -> String {
        var candidates: [URL] = []
        if let url = Bundle.main.url(forResource: "15-crop-genesis", withExtension: "frag", subdirectory: "shaders") {
            candidates.append(url)
        }
        let cwd = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        candidates.append(cwd.appendingPathComponent("../nexxhub/vis/shaders/15-crop-genesis.frag"))
        candidates.append(cwd.appendingPathComponent("nexxhub/vis/shaders/15-crop-genesis.frag"))
        candidates.append(cwd.appendingPathComponent("../vis/shaders/15-crop-genesis.frag"))
        candidates.append(cwd.appendingPathComponent("vis/shaders/15-crop-genesis.frag"))
        for url in candidates where FileManager.default.fileExists(atPath: url.path) {
            if let text = try? String(contentsOf: url, encoding: .utf8) { return text }
        }
        throw NSError(domain: "nexxvis", code: 4,
                      userInfo: [NSLocalizedDescriptionKey: "15-crop-genesis.frag not found"])
    }
}
