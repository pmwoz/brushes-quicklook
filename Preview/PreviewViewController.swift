import Cocoa
import Quartz
import SwiftUI

final class PreviewViewController: NSViewController, @preconcurrency QLPreviewingController {
    private static let previewTimeout: TimeInterval = 10
    private var request: (id: UUID, completion: (Error?) -> Void)?
    private(set) var preview: NSHostingView<PreviewGrid>?

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 760, height: 600))
    }

    func preparePreviewOfFile(at url: URL, completionHandler handler: @escaping (Error?) -> Void) {
        let id = beginPreview(completionHandler: handler)
        Task {
            let timeout = Self.previewTimeout
            let result: Result<BrushPreviewSet, any Error> = await withCheckedContinuation { continuation in
                DispatchQueue.global(qos: .userInitiated).async {
                    continuation.resume(returning: Result {
                        try BrushPreviewSet.load(url, maxCell: 160, timeout: timeout)
                    })
                }
            }
            finishPreview(id, result: result, fileName: url.lastPathComponent)
        }
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

    func finishPreview(_ id: UUID, result: Result<BrushPreviewSet, any Error>, fileName: String) {
        guard let active = request, active.id == id else { return }
        request = nil
        view.subviews.forEach { $0.removeFromSuperview() }
        switch result {
        case .success(let set):
            let hosted = NSHostingView(rootView: PreviewGrid(title: set.name ?? fileName, set: set))
            preview = hosted
            install(hosted)
            active.completion(nil)
        case .failure(let error):
            // Quick Look shows a message only for an NSError carrying NSLocalizedDescriptionKey.
            active.completion(NSError(
                domain: Bundle.main.bundleIdentifier ?? "BrushesPreview",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: error.localizedDescription]
            ))
        }
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
