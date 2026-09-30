import Cocoa
import Quartz
import SwiftUI

final class PreviewViewController: NSViewController, @preconcurrency QLPreviewingController {
    private var request: (id: UUID, completion: (Error?) -> Void)?
    private(set) var preview: NSHostingView<PreviewContent>?

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 760, height: 600))
    }

    func preparePreviewOfFile(at url: URL, completionHandler handler: @escaping (Error?) -> Void) {
        let id = beginPreview(completionHandler: handler)
        Task {
            finishPreview(id, result: await PreviewContent.loadGrid(url))
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

    func finishPreview(_ id: UUID, result: Result<PreviewGrid, any Error>) {
        guard let active = request, active.id == id else { return }
        request = nil
        view.subviews.forEach { $0.removeFromSuperview() }
        let hosted = NSHostingView(rootView: PreviewContent(result))
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
