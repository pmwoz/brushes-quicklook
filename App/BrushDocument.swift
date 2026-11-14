import SwiftUI
import UniformTypeIdentifiers

/// Reads nothing itself. The view loads the file from its URL through the preview's load path,
/// which refuses files above the size ceiling before reading them.
struct BrushDocument: FileDocument {
    static let readableContentTypes = ["abr", "brush", "brushset"].map {
        UTType(importedAs: "pl.esdesign.brushesquicklook.\($0)")
    }

    init(configuration: ReadConfiguration) {}

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        throw CocoaError(.featureUnsupported)
    }
}

struct BrushDocumentView: View {
    /// One load at a time, so opening many files at once does not hold many of them in memory together.
    private static let loads = DispatchQueue(label: "pl.esdesign.brushesquicklook.document-load", qos: .userInitiated)

    let url: URL
    @State private var content = PreviewContent.loading

    var body: some View {
        content
            .frame(minWidth: 480, minHeight: 360)
            .task(id: url) {
                content = .loading
                content = PreviewContent(await PreviewContent.loadGrid(url, on: Self.loads))
            }
    }
}
