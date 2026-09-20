import SwiftUI

struct ResultView: View {
    enum Display: String, CaseIterable, Identifiable {
        case text, json
        var id: String { rawValue }
        var title: String { self == .text ? "テキスト" : "JSON" }
    }

    let outcome: Outcome
    @State private var display: Display = .text
    @State private var copied = false
    @Environment(\.dismiss) private var dismiss

    private var shown: String {
        display == .text ? outcome.text : outcome.result.serialized(indent: 2, ensureASCII: false)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                Text(shown)
                    .font(.system(.footnote, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
            }
            .navigationTitle("status: " + outcome.status)
            .navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .top) {
                Picker("表示", selection: $display) {
                    ForEach(Display.allCases) { option in
                        Text(option.title).tag(option)
                    }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                .padding(.bottom, 8)
                .background(.bar)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("閉じる") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        UIPasteboard.general.string = shown
                        copied = true
                    } label: {
                        Label(copied ? "コピーしました" : "コピー", systemImage: copied ? "checkmark" : "doc.on.doc")
                    }
                }
            }
            .onChange(of: display) { _, _ in copied = false }
        }
    }
}
