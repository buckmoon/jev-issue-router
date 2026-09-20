import Foundation

/// Keeps the form inputs for the next launch, like the macOS app's draft.json.
/// Owner-only app container file; never the API key, the GitHub token or results.
struct Draft: Codable, Equatable {
    var url = ""
    var body = ""
    var context = ""
    var policy = Policies.names[0]

    var isEmpty: Bool {
        [url, body, context].allSatisfy { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }
}

enum DraftStore {
    static var url: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("jev-issue-router", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("draft.json")
    }

    static func load() -> Draft {
        guard let data = try? Data(contentsOf: url), var draft = try? JSONDecoder().decode(Draft.self, from: data)
        else { return Draft() }
        if !Policies.names.contains(draft.policy) { draft.policy = Policies.names[0] }
        return draft
    }

    static func save(_ draft: Draft) {
        if draft.isEmpty {
            try? FileManager.default.removeItem(at: url)
            return
        }
        guard let data = try? JSONEncoder().encode(draft) else { return }
        try? data.write(to: url, options: [.atomic, .completeFileProtection])
    }

    static func clear() {
        try? FileManager.default.removeItem(at: url)
    }
}
