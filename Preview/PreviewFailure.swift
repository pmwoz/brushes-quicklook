import AppKit
import SwiftUI

struct PreviewFailure: View {
    let message: String
    let details: String?

    nonisolated init(error: any Error) {
        switch error as? BrushPreviewError {
        case .damaged(let parserMessage):
            message = "The file looks damaged or incomplete."
            details = parserMessage
        case .unsupportedExtension, .tooLarge, .timedOut, nil:
            message = error.localizedDescription
            details = nil
        }
    }

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 40))
                .foregroundStyle(.secondary)
                .opacity(0.7)
                .padding(.bottom, 8)
                .accessibilityHidden(true)
            Text("This file can’t be previewed")
                .font(.system(size: 17, weight: .semibold))
            Text(message)
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .lineSpacing(2)
                .frame(maxWidth: 420)
            if let details {
                DisclosureGroup("Details") {
                    Text(details)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.leading)
                        .textSelection(.enabled)
                        .padding(.vertical, 8)
                        .padding(.horizontal, 10)
                        .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 6))
                }
                .disclosureGroupStyle(CenteredDisclosure())
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .frame(maxWidth: 520)
                .padding(.top, 14)
            }
        }
        .multilineTextAlignment(.center)
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

/// The system style pins the label to the leading edge, which looks stray under centred text.
private struct CenteredDisclosure: DisclosureGroupStyle {
    func makeBody(configuration: Configuration) -> some View {
        VStack(spacing: 6) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { configuration.isExpanded.toggle() }
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 9, weight: .semibold))
                        .rotationEffect(.degrees(configuration.isExpanded ? 90 : 0))
                    configuration.label
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if configuration.isExpanded {
                configuration.content
            }
        }
    }
}
