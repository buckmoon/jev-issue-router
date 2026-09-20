import CryptoKit
import Foundation

struct Question {
    let name: String
    let criteria: [(String, String)]
    let instructions: String

    var json: JSONValue {
        .fields([("type", .string("choice")), ("criteria", .strings(criteria)),
                 ("instructions", .string(instructions))])
    }
}

struct ValidatedAnswer {
    let choice: String
    let probabilities: [(key: String, value: Double)]
    let confidence: Double
    /// The answer exactly as Jev returned it; sent back to Jev and stored in the result unchanged.
    let raw: JSONValue

    func probability(_ key: String) -> Double {
        probabilities.first { $0.key == key }?.value ?? 0
    }
}

/// Port of `issue_router/core.py:route`. Two Jev calls: assess the issue, then select one model and
/// effort per provider. Nothing is recommended when Jev abstains; recommendations are never invented.
enum Router {
    static let providers = Catalog.providers
    static let policyVersion = "2026-09-20.4"
    static let maxInputChars = 60000
    static let topCandidates = 5

    static func normalizeIssue(title: String = "", body: String = "", context: String = "") throws -> [(String, String)] {
        let issue = [("title", title), ("body", body), ("context", context)]
        guard issue.contains(where: { !$0.1.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else {
            throw RouterError("Issue is empty")
        }
        // Python's len() counts code points, so the limit is measured in unicode scalars here too.
        guard issue.reduce(0, { $0 + $1.1.unicodeScalars.count }) <= maxInputChars else {
            throw RouterError("入力が60,000文字を超えています。要点をまとめて入力してください（自動で切り詰めません）")
        }
        return issue
    }

    static func validate(_ response: JSONValue, questions: [Question]) throws -> [String: ValidatedAnswer] {
        guard let answers = response["answers"], answers.isObject else {
            throw RouterError("Invalid Jev response")
        }
        var validated: [String: ValidatedAnswer] = [:]
        for question in questions {
            guard let answer = answers[question.name], answer.isObject else {
                throw RouterError("Invalid Jev answer type")
            }
            let options = Set(question.criteria.map(\.0))
            guard answer["type"]?.stringValue == "choice", let choice = answer["choice"]?.stringValue,
                  options.contains(choice), let probabilities = answer["probabilities"]?.objectValue,
                  let confidence = answer["confidence"]?.doubleValue, isProbability(confidence) else {
                throw RouterError("Invalid or incomplete Jev choice/probabilities")
            }
            var values: [(key: String, value: Double)] = []
            for pair in probabilities {
                guard let value = pair.value.doubleValue, isProbability(value) else {
                    throw RouterError("Invalid or incomplete Jev choice/probabilities")
                }
                values.append((key: pair.key, value: value))
            }
            let total = values.reduce(0) { $0 + $1.value }
            guard Set(values.map(\.key)) == options, abs(total - 1) <= 0.02 else {
                throw RouterError("Invalid or incomplete Jev choice/probabilities")
            }
            let chosen = values.first { $0.key == choice }?.value ?? 0
            // Probabilities arrive rounded to two decimals, so a near-tie may show the choice 0.01 below the top.
            guard chosen + 0.015 >= (values.map(\.value).max() ?? 0) else {
                throw RouterError("Jev choice disagrees with highest probability")
            }
            validated[question.name] = ValidatedAnswer(choice: choice, probabilities: values,
                                                       confidence: confidence, raw: answer)
        }
        return validated
    }

    private static func isProbability(_ value: Double) -> Bool {
        value.isFinite && value >= 0 && value <= 1
    }

    static func route(issue: [(String, String)], catalog: Catalog, policy: String,
                      jevModel: String = JevClient.defaultModel,
                      evaluate: (JSONValue) async throws -> JSONValue) async throws -> JSONValue {
        guard Policies.names.contains(policy), let objective = Policies.objectives[policy] else {
            throw RouterError("Unknown policy")
        }
        let evidence: [(String, JSONValue)] = [("issue", .strings(issue))]
        let guardText = Rubrics.guardText

        var questions: [Question] = Rubrics.names.map { name in
            Question(name: name, criteria: Rubrics.criteria[name] ?? [],
                     instructions: guardText + "Classify the issue's \(name) using the supplied criteria.")
        }
        questions += Rubrics.contextNames.map { name in
            Question(name: "context_" + name, criteria: Rubrics.contextCriteria[name] ?? [],
                     instructions: guardText
                        + "Decide only whether the supplied evidence covers this aspect of the task: \(name).")
        }
        let first = try await evaluate(request(model: jevModel, state: evidence, questions: questions))
        let answers = try validate(first, questions: questions)
        let assessment = Rubrics.names.compactMap { name in answers[name].map { (name, $0) } }
        let missing = Rubrics.contextNames.filter { answers["context_" + $0]?.choice == "missing" }

        var warnings = ["確率・confidenceは実装成功率ではありません。選定ルールは実Issueで未校正です。",
                        "APIのモデルID・推論設定です。各CLI/UIの対応やアカウント利用可否は別途確認が必要です。"]
        if Policies.topModel.contains(policy) {
            warnings.append("この方針はモデルを各社の最上位（カタログの最後）に固定します。Jevが選んだのは推論設定です。")
        }
        if Policies.guidance[policy]?.costBasis != nil {
            warnings.append("コストは定性的な判断です。料金・所要時間・手戻り・節約額の実測や算出はしていません。")
        }
        if Calendar(identifier: .gregorian).dateComponents([.day], from: catalog.verifiedAt, to: Date()).day ?? 0 > 30 {
            warnings.append("モデルカタログの確認から30日超過しています。公式仕様を再確認してください。")
        }

        var calls: [JSONValue] = [call(first)]
        func result(status: String, recommendations: [(String, JSONValue)]) -> JSONValue {
            .fields([
                ("schema_version", .int(1)),
                ("policy_version", .string(policyVersion)),
                ("policy", .string(policy)),
                ("selection_objective", .string(objective)),
                ("catalog_version", .string(catalog.version)),
                ("catalog_verified_at", .string(catalog.verifiedAtText)),
                ("created_at", .string(timestamp())),
                ("input_sha256", .string(hash(issue))),
                ("status", .string(status)),
                ("assessment", .fields(assessment.map { ($0.0, $0.1.raw) })),
                ("missing_context", .array(missing.map { .string($0) })),
                ("recommendations", .fields(recommendations)),
                ("jev_calls", .array(calls)),
                ("warnings", .array(warnings.map { .string($0) })),
            ])
        }

        // Abstain when Jev finds the task unready, unless the only named gaps are refinements.
        let refinementsOnly = !missing.isEmpty && Set(missing).isSubset(of: Rubrics.nonBlockingContext)
        if answers["readiness"]?.choice == "insufficient" && !refinementsOnly {
            return result(status: "needs_context", recommendations: [])
        }

        var selectionQuestions: [Question] = []
        var lookup: [String: [String: (model: CatalogModel, effort: String)]] = [:]
        for provider in providers {
            var criteria: [(String, String)] = [("needs_context",
                "The requested work cannot be understood well enough to select any pair. "
                + "Open details, listed missing_context or an imperfect fit are not reasons "
                + "to select this; choose the closest supported pair instead.")]
            var pairs: [String: (model: CatalogModel, effort: String)] = [:]
            let models = catalog.models(for: provider)
            for (index, model) in models.enumerated() {
                let position = index + 1
                if Policies.topModel.contains(policy) && position < models.count {
                    continue  // the policy fixes the model to the provider's most capable; Jev selects the effort
                }
                for (level, effort) in model.efforts.enumerated() {
                    let choice = model.id + "__" + effort
                    var text = model.selectionGuidance + " Effort: " + catalog.guidance(for: effort)
                    if Policies.ordinal.contains(policy) {
                        // The catalog lists each provider's models from most economical to most capable.
                        text += " Catalog position: model \(position) of \(models.count) for this provider "
                            + "(1 = most economical, \(models.count) = most capable); effort level "
                            + "\(level + 1) of \(model.efforts.count) (1 = lowest spend)."
                    }
                    criteria.append((choice, text))
                    pairs[choice] = (model: model, effort: effort)
                }
            }
            guard criteria.count <= 255 else { throw RouterError("Jev supports at most 255 choices per question") }
            lookup[provider] = pairs
            selectionQuestions.append(Question(name: provider, criteria: criteria, instructions: guardText
                + "Select one \(provider) model and effort pair for implementing this issue. "
                + "Apply only the selected policy '\(policy)': \(objective) "
                + "Use catalog guidance as provisional routing policy, not measured success rates. "
                + "Consider assessment probabilities, not just their winning labels. High risk warrants careful "
                + "verification but does not automatically mean maximum effort. `missing_context` lists task "
                + "aspects the issue leaves open, and an 'unknown' assessment means the issue does not settle that "
                + "aspect. The goal is known, so the implementing model will have to plan the work and make those "
                + "decisions itself: treat open aspects as added difficulty that favors a pair capable of planning "
                + "under ambiguity, not as grounds to abstain. Select needs_context only if no pair can be "
                + "distinguished at all."))
        }

        let state: [(String, JSONValue)] = evidence + [
            ("assessment", .fields(assessment.map { ($0.0, $0.1.raw) })),
            ("missing_context", .array(missing.map { .string($0) })),
            ("policy", .string(policy)),
        ]
        let second = try await evaluate(request(model: jevModel, state: state, questions: selectionQuestions))
        let selections = try validate(second, questions: selectionQuestions)
        calls.append(call(second))

        var recommendations: [(String, JSONValue)] = []
        var chosen: [Bool] = []
        for provider in providers {
            guard let answer = selections[provider], let pairs = lookup[provider] else { continue }
            var entry: [(String, JSONValue)] = [("judgment", answer.raw)]
            if answer.choice == "needs_context" {
                // Jev withheld a single pick; report where its probability went instead of inventing one.
                let ranked = rankedDescending(answer.probabilities.filter {
                    $0.key != "needs_context" && $0.value > 0
                }).prefix(topCandidates)
                entry.append(("status", .string("needs_context")))
                entry.append(("top_candidates", .array(ranked.compactMap { candidate in
                    guard let pair = pairs[candidate.key] else { return nil }
                    return .fields([("model", .string(pair.model.id)), ("effort", .string(pair.effort)),
                                    ("probability", .double(candidate.value))])
                })))
                chosen.append(false)
            } else if let pair = pairs[answer.choice] {
                var parameters: [(String, JSONValue)] = [("model", .string(pair.model.id))]
                if pair.model.provider == "claude" {
                    parameters.append(("thinking", .strings([("type", "adaptive")])))
                    parameters.append(("output_config", .strings([("effort", pair.effort)])))
                } else {
                    parameters.append(("reasoning", .strings([("effort", pair.effort)])))
                }
                entry.append(("status", .string("selected")))
                entry.append(("model", .string(pair.model.id)))
                entry.append(("effort", .string(pair.effort)))
                entry.append(("api_parameters", .fields(parameters)))
                entry.append(("selection_guidance", .string(pair.model.selectionGuidance)))
                entry.append(("sources", .array(pair.model.sources.map { .string($0) })))
                if let guidance = Policies.guidance[policy] {
                    entry.append(("policy_guidance", guidance.json))
                }
                chosen.append(true)
            } else {
                throw RouterError("Invalid or incomplete Jev choice/probabilities")
            }
            recommendations.append((provider, .fields(entry)))
        }
        let status = chosen.allSatisfy { $0 } && !chosen.isEmpty ? "selected"
            : chosen.contains(true) ? "partial" : "needs_context"
        return result(status: status, recommendations: recommendations)
    }

    /// Highest probability first, keeping Jev's own order for ties, like Python's stable `sorted`.
    static func rankedDescending(_ items: [(key: String, value: Double)]) -> [(key: String, value: Double)] {
        items.enumerated()
            .sorted { $0.element.value != $1.element.value ? $0.element.value > $1.element.value : $0.offset < $1.offset }
            .map(\.element)
    }

    private static func request(model: String, state: [(String, JSONValue)], questions: [Question]) -> JSONValue {
        .fields([("model", .string(model)), ("state", .fields(state)),
                 ("questions", .fields(questions.map { ($0.name, $0.json) }))])
    }

    private static func call(_ response: JSONValue) -> JSONValue {
        .fields([("model", response["model"] ?? .null), ("usage", response["usage"] ?? .null)])
    }

    private static func hash(_ issue: [(String, String)]) -> String {
        let canonical = JSONValue.strings(issue).serialized(sortKeys: true)
        return SHA256.hash(data: Data(canonical.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func timestamp() -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        return formatter.string(from: Date()) + "+00:00"
    }
}
