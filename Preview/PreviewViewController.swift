import Cocoa
import Quartz

final class PreviewViewController: NSViewController, @preconcurrency QLPreviewingController {
    private let label = NSTextField(labelWithString: "")

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 640, height: 240))
        label.alignment = .center
        label.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(label)
        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            label.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            label.leadingAnchor.constraint(greaterThanOrEqualTo: view.leadingAnchor, constant: 20),
            label.trailingAnchor.constraint(lessThanOrEqualTo: view.trailingAnchor, constant: -20),
        ])
    }

    func preparePreviewOfFile(at url: URL, completionHandler handler: @escaping (Error?) -> Void) {
        do {
            let set = try BrushPreviewSet.load(url, maxCell: 160)
            label.stringValue = "\(set.name ?? url.lastPathComponent) · \(set.entries.count) brushes"
            handler(nil)
        } catch {
            // Quick Look shows a message only for an NSError carrying NSLocalizedDescriptionKey.
            handler(NSError(
                domain: Bundle.main.bundleIdentifier ?? "BrushesPreview",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: error.localizedDescription]
            ))
        }
    }
}
