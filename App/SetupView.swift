import AppKit
import SwiftUI

struct SetupView: View {
    /// Opens the Quick Look sheet of General > Login Items & Extensions, or on macOS 14 the
    /// Privacy & Security > Extensions list.
    static let extensionSettings = URL(
        string: "x-apple.systempreferences:com.apple.ExtensionsPreferences?extensionPointIdentifier=com.apple.quicklook.preview"
    )!

    private static let extensionSettingsPath = if #available(macOS 15, *) {
        "System Settings › General › Login Items & Extensions › Quick Look"
    } else {
        "System Settings › Privacy & Security › Extensions › Quick Look"
    }

    @Environment(\.openURL) private var openURL
    @Environment(\.openDocument) private var openDocument
    @State private var isDropTargeted = false

    var body: some View {
        VStack(spacing: 8) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 88, height: 88)
                .padding(.bottom, 8)
                .accessibilityHidden(true)
            Text("Brushes Quick Look")
                .font(.title2.weight(.semibold))
            Text("Finder thumbnails and space-bar previews for Photoshop .abr and Procreate .brush and .brushset files.")
                .font(.body)
                .foregroundStyle(.secondary)
                .lineSpacing(2)
            VStack(spacing: 4) {
                Text("To finish setup, turn on BrushesPreview and BrushesThumbnail.")
                    .font(.body)
                Text(Self.extensionSettingsPath)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .padding(.top, 12)
            HStack(spacing: 12) {
                Button("Open System Settings") { openURL(Self.extensionSettings) }
                    .keyboardShortcut(.defaultAction)
                Button("Open Brush File…") { NSDocumentController.shared.openDocument(nil) }
            }
            .controlSize(.large)
            .padding(.top, 12)
            Text("You can also drop brush files on this window to see every brush in them.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .padding(.top, 12)
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
