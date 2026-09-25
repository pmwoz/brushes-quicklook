import Cocoa
import Quartz
import SwiftUI

final class PreviewViewController: NSViewController, @preconcurrency QLPreviewingController {
    private static let previewTimeout: TimeInterval = 10
    private var request: (id: UUID, completion: (Error?) -> Void)?
    private(set) var preview: NSHostingView<PreviewContent>?

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 760, height: 600))
    }

    func preparePreviewOfFile(at url: URL, completionHandler handler: @escaping (Error?) -> Void) {
        let id = beginPreview(completionHandler: handler)
        Task {
            let timeout = Self.previewTimeout
            let result: Result<(BrushFormat, BrushPreviewSet), any Error> = await withCheckedContinuation { continuation in
                DispatchQueue.global(qos: .userInitiated).async {
                    continuation.resume(returning: Result {
                        (try BrushFormat(url: url), try Self.load(url, timeout: timeout))
                    })
                }
            }
            finishPreview(id, result: result.map { format, set in
                PreviewGrid(fileName: url.lastPathComponent, format: format, set: set)
            })
        }
    }

    /// A single brush fills a 380 pt well, so it is decoded again at a size that stays sharp there.
    private nonisolated static func load(_ url: URL, timeout: TimeInterval) throws -> BrushPreviewSet {
        let set = try BrushPreviewSet.load(url, maxCell: 256, timeout: timeout)
        guard set.entries.count == 1 else { return set }
        return try BrushPreviewSet.load(url, maxCell: 768, timeout: timeout)
    }

    func beginPreview(completionHandler: @escaping (Error?) -> Void) -> UUID {
        let previous = request
        let id = UUID()
        request = (id, completionHandler)
        preview = nil
        view.subviews.forEach { $0.removeFromSuperview() }
        let loading = NSTextField(labelWithString: "Loading brushes…")
        loading.alignment = .center
        install(loading)
        previous?.completion(NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError))
        return id
    }

    func finishPreview(_ id: UUID, result: Result<PreviewGrid, any Error>) {
        guard let active = request, active.id == id else { return }
        request = nil
        view.subviews.forEach { $0.removeFromSuperview() }
        let content: PreviewContent = switch result {
        case .success(let grid): .grid(grid)
        case .failure(let error): .failure(PreviewFailure(error: error))
        }
        let hosted = NSHostingView(rootView: content)
        preview = hosted
        install(hosted)
        active.completion(nil)
    }

    private func install(_ content: NSView) {
        content.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(content)
        NSLayoutConstraint.activate([
            content.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            content.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            content.topAnchor.constraint(equalTo: view.topAnchor),
            content.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
    }
}

enum PreviewContent: View {
    case grid(PreviewGrid)
    case failure(PreviewFailure)

    var body: some View {
        switch self {
        case .grid(let grid): grid
        case .failure(let failure): failure
        }
    }
}
