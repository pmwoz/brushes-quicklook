import SwiftUI

@main
struct BrushesQuickLookApp: App {
    var body: some Scene {
        WindowGroup {
            VStack(spacing: 20) {
                Text("Brushes Quick Look")
                    .font(.title)
                Text("Move the app to Applications and open it once. macOS registers the extensions on first launch.")
                Text("If Finder still shows generic icons, enable them under System Settings > General > Login Items & Extensions > Quick Look.")
            }
            .multilineTextAlignment(.center)
            .padding(32)
            .frame(width: 480, height: 260)
        }
        .windowResizability(.contentSize)
    }
}
