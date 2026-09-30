import SwiftUI

@main
struct BrushesQuickLookApp: App {
    var body: some Scene {
        Window("Brushes Quick Look", id: "setup") {
            SetupView()
        }
        .windowResizability(.contentSize)

        DocumentGroup(viewing: BrushDocument.self) { file in
            BrushDocumentView(url: file.fileURL)
        }
        .defaultSize(width: 760, height: 600)
    }
}
