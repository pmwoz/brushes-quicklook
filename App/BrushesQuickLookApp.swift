import SwiftUI

@main
struct BrushesQuickLookApp: App {
    var body: some Scene {
        Window("Brushes Quick Look", id: "setup") {
            SetupView()
        }
        .windowResizability(.contentSize)

        DocumentGroup(viewing: BrushDocument.self) { file in
            if let url = file.fileURL {
                BrushDocumentView(url: url)
            } else {
                PreviewFailure(error: CocoaError(.fileReadUnknown))
            }
        }
        .defaultSize(width: 760, height: 600)
    }
}
