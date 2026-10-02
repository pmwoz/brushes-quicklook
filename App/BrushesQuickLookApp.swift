import SwiftUI

@main
struct BrushesQuickLookApp: App {
    private static let editingActions: Set<Selector> = [
        #selector(NSDocument.save(_:)),
        #selector(NSDocument.saveAs(_:)),
        #selector(NSDocument.duplicate(_:)),
        #selector(NSDocument.rename(_:)),
        #selector(NSDocument.move(_:)),
        #selector(NSDocument.revertToSaved(_:)),
    ]

    init() {
        Task {
            let additions = NotificationCenter.default.notifications(named: NSMenu.didAddItemNotification)
            Self.removeEditingItems()
            // SwiftUI re-adds DocumentGroup's NSDocument items to the File menu when a document window closes.
            for await _ in additions {
                Self.removeEditingItems()
            }
        }
    }

    private static func removeEditingItems() {
        for menu in NSApp.mainMenu?.items.compactMap(\.submenu) ?? [] {
            for item in menu.items {
                guard let action = item.action, editingActions.contains(action) else { continue }
                let next = menu.index(of: item) + 1
                // AppKit puts the "Revert To" submenu right after this item. The submenu is empty until it
                // opens and shares its delegate class with Open Recent and Share, so position is its only identifier.
                if action == #selector(NSDocument.revertToSaved(_:)), next < menu.numberOfItems,
                   menu.item(at: next)?.hasSubmenu == true {
                    menu.removeItem(at: next)
                }
                menu.removeItem(item)
            }
        }
    }

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
