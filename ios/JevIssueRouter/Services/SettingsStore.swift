import Foundation

/// The evaluator choice, like the macOS app's settings.json. Non-secret fields only: the Cloudflare token lives in
/// the Keychain. The account ID is an identifier, not a secret, but it never goes into the result JSON.
struct EvaluatorSettings: Codable, Equatable {
    var evaluator = "jev"
    var clefModel = "clef"
    /// Empty means "same as clefModel" (the accuracy-first and fast presets).
    var clefAssessModel = ""
    var cloudflareAccountID = ""

    enum CodingKeys: String, CodingKey {
        case evaluator, clefModel = "clef_model", clefAssessModel = "clef_assess_model"
        case cloudflareAccountID = "cloudflare_account_id"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let defaults = EvaluatorSettings()
        evaluator = (try? container.decode(String.self, forKey: .evaluator)) ?? defaults.evaluator
        clefModel = (try? container.decode(String.self, forKey: .clefModel)) ?? defaults.clefModel
        clefAssessModel = (try? container.decode(String.self, forKey: .clefAssessModel)) ?? defaults.clefAssessModel
        cloudflareAccountID = (try? container.decode(String.self, forKey: .cloudflareAccountID)) ?? defaults.cloudflareAccountID
    }

    /// Validates like make_evaluator; throws before any network call.
    func makeEvaluator() throws -> Evaluator {
        switch evaluator {
        case "jev":
            return .jev()
        case "clef":
            return try .workersAI(accountID: cloudflareAccountID.trimmingCharacters(in: .whitespacesAndNewlines),
                                  model: clefModel, assessModel: clefAssessModel)
        default:
            throw RouterError("評価モデルは jev か clef です")
        }
    }

    var label: String { Evaluator.labels[evaluator] ?? "Jev" }
    var keychainService: String { Evaluator.keychainServices[evaluator] ?? Keychain.typesafeService }
}

enum SettingsStore {
    static var url: URL {
        DraftStore.url.deletingLastPathComponent().appendingPathComponent("settings.json")
    }

    static func load() -> EvaluatorSettings {
        guard let data = try? Data(contentsOf: url),
              let settings = try? JSONDecoder().decode(EvaluatorSettings.self, from: data) else {
            return EvaluatorSettings()
        }
        return settings
    }

    /// Saves only settings that pass validation, so the app never evaluates with a half-typed account ID.
    static func save(_ settings: EvaluatorSettings) throws {
        _ = try settings.makeEvaluator()
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        guard let data = try? encoder.encode(settings) else { throw RouterError("設定を保存できません") }
        do {
            try data.write(to: url, options: [.atomic, .completeFileProtection])
        } catch {
            throw RouterError("設定を保存できません")
        }
    }
}
