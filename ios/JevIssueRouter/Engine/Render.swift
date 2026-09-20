import Foundation

/// Port of `issue_router/core.py:render`: the same Japanese summary the CLI and macOS app print.
enum Render {
    static func text(_ result: JSONValue) -> String {
        var lines = ["Jev モデル推薦（暫定）", ""]
        let status = result["status"]?.stringValue ?? "needs_context"
        let recommendations = result["recommendations"]

        for provider in Router.providers {
            guard let rec = recommendations?[provider], rec["status"]?.stringValue == "selected" else {
                let rec = recommendations?[provider]
                let reason = rec != nil && status == "partial" ? "Jevが候補を1つに絞れませんでした" : "情報不足"
                lines.append("• \(provider): 選定保留（\(reason)）")
                let candidates = rec?["top_candidates"]?.arrayValue ?? []
                if !candidates.isEmpty {
                    let held = rec?["judgment"]?["probabilities"]?["needs_context"]?.doubleValue ?? 0
                    lines.append("  確率が割れた上位候補（選定保留 \(percent(held))）。推薦ではなく、判断材料としての内訳です:")
                    for (index, candidate) in candidates.enumerated() {
                        let model = candidate["model"]?.stringValue ?? "?"
                        let effort = candidate["effort"]?.stringValue ?? "?"
                        let probability = candidate["probability"]?.doubleValue ?? 0
                        lines.append("  \(index + 1). \(model) / \(effort) (\(percent(probability)))")
                    }
                }
                continue
            }
            let judgment = rec["judgment"]
            let choice = judgment?["choice"]?.stringValue ?? ""
            let probabilities = judgment?["probabilities"]?.objectValue ?? []
            let probability = probabilities.first { $0.key == choice }?.value.doubleValue ?? 0
            let confidence = judgment?["confidence"]?.doubleValue ?? 0
            let model = rec["model"]?.stringValue ?? "?"
            let effort = rec["effort"]?.stringValue ?? "?"
            lines.append("• \(provider): \(model) / \(effort) "
                + "(選択確率 \(percent(probability)), confidence \(String(format: "%.2f", confidence)))")
            let alternatives = Router.rankedDescending(probabilities.compactMap { pair in
                guard pair.key != choice, let value = pair.value.doubleValue, value > 0 else { return nil }
                return (key: pair.key, value: value)
            })
            if let best = alternatives.first {
                let label = best.key == "needs_context" ? "選定保留"
                    : best.key.replacingOccurrences(of: "__", with: " / ")
                lines.append("  次候補: \(label) (\(percent(best.value)))")
            }
        }

        lines += ["", "選定に使った評価:"]
        for (name, answer) in result["assessment"]?.objectValue ?? [] {
            let choice = answer["choice"]?.stringValue ?? ""
            let probability = answer["probabilities"]?[choice]?.doubleValue ?? 0
            lines.append("• \(Rubrics.label(name)): \(Rubrics.label(choice)) (\(percent(probability)))")
        }

        let missing = (result["missing_context"]?.arrayValue ?? [])
            .compactMap { $0.stringValue }
            .compactMap { Rubrics.contextHints[$0] }
        if status == "selected" && !missing.isEmpty {
            lines += ["", "暫定の選定です。次の情報は本文にありませんでした。補足して再評価すると判断の確度が上がります:"]
            lines += missing.map { "• " + $0 }
        }
        if status == "partial" {
            lines += ["", "一部の会社は選定を保留しました。他社の結果は有効です。"]
            if !missing.isEmpty {
                lines += ["次の情報を補足して再評価すると、保留が解消しやすくなります:"] + missing.map { "• " + $0 }
            }
        } else if status != "selected" {
            if !missing.isEmpty {
                lines += ["", "選定を保留しました。Jevが不足と判断した情報:"] + missing.map { "• " + $0 }
                lines.append("これらを本文か追加コンテキストに補足して再評価してください。")
            } else {
                lines += ["", "期待する動作・現状・変更範囲・完了条件を補足して再評価してください。"]
            }
        }

        lines += ["", "方針: \(result["policy"]?.stringValue ?? "") / カタログ: \(result["catalog_version"]?.stringValue ?? "")"]

        let advice = Router.providers
            .compactMap { recommendations?[$0] }
            .first { $0["status"]?.stringValue == "selected" && $0["policy_guidance"] != nil }?["policy_guidance"]
        if let advice {
            lines += ["", advice["summary"]?.stringValue ?? "", advice["next_step"]?.stringValue ?? "",
                      "再評価の目安: " + (advice["reevaluate_when"]?.stringValue ?? ""),
                      "得られた情報を追加して 方針 \(advice["reevaluation_policy"]?.stringValue ?? "") で再評価できます。自動切替は行いません。"]
        }
        lines += (result["warnings"]?.arrayValue ?? []).compactMap { $0.stringValue }
        return lines.joined(separator: "\n")
    }

    private static func percent(_ value: Double) -> String {
        String(format: "%.0f%%", value * 100)
    }
}

