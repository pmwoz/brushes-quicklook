import AppKit
import SwiftUI

struct SetupView: View {
    /// Opens the Quick Look sheet of System Settings > General > Login Items & Extensions.
    static let extensionSettings = URL(
        string: "x-apple.systempreferences:com.apple.ExtensionsPreferences?extensionPointIdentifier=com.apple.quicklook.preview"
    )!

    @Environment(\.openURL) private var openURL
    @Environment(\.openDocument) private var openDocument
    @State private var isDropTargeted = false

    var body: some View {
        VStack(spacing: 6) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 88, height: 88)
                .padding(.bottom, 8)
                .accessibilityHidden(true)
            Text("Brushes Quick Look")
                .font(.system(size: 17, weight: .semibold))
            Text("Finder thumbnails and space-bar previews for Photoshop .abr and Procreate .brush and .brushset files.")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .lineSpacing(2)
            Text("To finish setup, turn on BrushesPreview and BrushesThumbnail in the Quick Look extensions of System Settings.")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .lineSpacing(2)
                .padding(.top, 10)
            HStack(spacing: 12) {
                Button("Open System Settings") { openURL(Self.extensionSettings) }
                    .keyboardShortcut(.defaultAction)
                Button("Open Brush File…") { NSDocumentController.shared.openDocument(nil) }
            }
            .controlSize(.large)
            .padding(.top, 18)
            Text("You can also drop brush files on this window to see every brush in them.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .padding(.top, 18)
        }
        .multilineTextAlignment(.center)
        .fixedSize(horizontal: false, vertical: true)
        .frame(width: 440)
        .padding(40)
        .background(Color(nsColor: .windowBackgroundColor))
        .overlay {
            if isDropTargeted {
                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(Color.accentColor, lineWidth: 3)
                    .padding(6)
            }
        }
        .dropDestination(for: URL.self) { urls, _ in
            let brushFiles = urls.filter { (try? BrushFormat(url: $0)) != nil }
            Task {
                for url in brushFiles {
                    do {
                        try await openDocument(at: url)
                    } catch {
                        NSApp.presentError(error)
                    }
                }
            }
            return !brushFiles.isEmpty
        } isTargeted: {
            isDropTargeted = $0
        }
    }
}
