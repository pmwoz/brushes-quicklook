import SwiftUI

enum PreviewContent: View {
    case grid(PreviewGrid)
    case failure(PreviewFailure)

    init(_ result: Result<PreviewGrid, any Error>) {
        self = switch result {
        case .success(let grid): .grid(grid)
        case .failure(let error): .failure(PreviewFailure(error: error))
        }
    }

    /// The space-bar preview and the app's document window both load through here, so they show the same thing.
    static func loadGrid(_ url: URL) async -> Result<PreviewGrid, any Error> {
        let result: Result<(BrushFormat, BrushPreviewSet), any Error> = await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                continuation.resume(returning: Result {
                    let format = try BrushFormat(url: url)
                    return (format, try BrushPreviewSet.load(url, budget: .preview(format)))
                })
            }
        }
        return result.map { format, set in
            PreviewGrid(fileName: url.lastPathComponent, format: format, set: set)
        }
    }

    var body: some View {
        switch self {
        case .grid(let grid): grid
        case .failure(let failure): failure
        }
    }
}
