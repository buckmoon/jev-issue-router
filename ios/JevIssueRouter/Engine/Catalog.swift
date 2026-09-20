import Foundation

struct RouterError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

struct CatalogModel {
    let id: String
    let provider: String
    let efforts: [String]
    let selectionGuidance: String
    let sources: [String]
    let enabled: Bool
}

/// Mirrors `issue_router/core.py:validate_catalog`. The bundled file is a copy of the repository catalog.
struct Catalog {
    static let providers = ["openai", "claude", "grok"]

    let version: String
    let verifiedAt: Date
    let verifiedAtText: String
    let effortGuidance: [(key: String, value: String)]
    let models: [CatalogModel]

    func guidance(for effort: String) -> String {
        effortGuidance.first { $0.key == effort }?.value ?? ""
    }

    func models(for provider: String) -> [CatalogModel] {
        models.filter { $0.provider == provider && $0.enabled }
    }

    static func bundled() throws -> Catalog {
        guard let url = Bundle.main.url(forResource: "catalog", withExtension: "json"),
              let data = try? Data(contentsOf: url) else {
            throw RouterError("モデルカタログを読み込めません")
        }
        guard let json = try? JSONValue.decode(data) else {
            throw RouterError("モデルカタログのJSONが不正です")
        }
        return try Catalog(json)
    }

    init(_ json: JSONValue) throws {
        guard json.isObject, let version = json["version"]?.stringValue,
              let models = json["models"]?.arrayValue,
              let guidancePairs = json["effort_guidance"]?.objectValue else {
            throw RouterError("Invalid catalog structure")
        }
        guard let verifiedText = json["verified_at"]?.stringValue,
              let verified = Self.isoDate.date(from: verifiedText) else {
            throw RouterError("Catalog verified_at must be YYYY-MM-DD")
        }
        var guidance: [(key: String, value: String)] = []
        for pair in guidancePairs {
            guard let text = pair.value.stringValue else { throw RouterError("Invalid catalog effort guidance") }
            guidance.append((key: pair.key, value: text))
        }
        guard !guidance.isEmpty else { throw RouterError("Invalid catalog effort guidance") }

        var parsed: [CatalogModel] = []
        var seen = Set<String>()
        for model in models {
            guard let id = model["id"]?.stringValue, let provider = model["provider"]?.stringValue,
                  Self.providers.contains(provider), Self.isModelIdentifier(id),
                  !seen.contains(id) else {
                throw RouterError("Invalid provider or duplicate model in catalog")
            }
            seen.insert(id)
            let efforts = (model["efforts"]?.arrayValue ?? []).compactMap { $0.stringValue }
            guard !efforts.isEmpty, efforts.count == (model["efforts"]?.arrayValue ?? []).count,
                  Set(efforts).count == efforts.count,
                  efforts.allSatisfy({ effort in guidance.contains { $0.key == effort } }) else {
                throw RouterError("Invalid effort in catalog")
            }
            let sources = (model["sources"]?.arrayValue ?? []).compactMap { $0.stringValue }
            var enabled = true
            if let flag = model["enabled"] {
                guard case let .bool(value) = flag else {
                    throw RouterError("Invalid model guidance, sources or enabled flag")
                }
                enabled = value
            }
            guard let selectionGuidance = model["selection_guidance"]?.stringValue,
                  !sources.isEmpty, sources.allSatisfy({ $0.hasPrefix("https://") }) else {
                throw RouterError("Invalid model guidance, sources or enabled flag")
            }
            parsed.append(CatalogModel(id: id, provider: provider, efforts: efforts,
                                       selectionGuidance: selectionGuidance, sources: sources, enabled: enabled))
        }
        for provider in Self.providers {
            let pairs = parsed.filter { $0.provider == provider && $0.enabled }.reduce(0) { $0 + $1.efforts.count }
            if pairs > 254 {
                throw RouterError("Jev supports at most 254 model/effort pairs plus the abstention option")
            }
        }
        self.version = version
        self.verifiedAt = verified
        self.verifiedAtText = verifiedText
        self.effortGuidance = guidance
        self.models = parsed
    }

    /// Catalog model ids stay restricted to the characters the Python engine accepts.
    private static func isModelIdentifier(_ id: String) -> Bool {
        !id.isEmpty && id.unicodeScalars.allSatisfy { scalar in
            ("A"..."Z").contains(String(scalar)) || ("a"..."z").contains(String(scalar))
                || ("0"..."9").contains(String(scalar)) || scalar == "." || scalar == "-"
        }
    }

    private static let isoDate: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
}
