import AppKit

@MainActor
enum FileMenu {
    private static let keptActions: Set<Selector> = [
        #selector(NSDocumentController.openDocument(_:)),
        #selector(NSWindow.performClose(_:)),
        Selector(("closeAll:")),
    ]

    // The Share submenu stays empty until it opens, and its delegate, target and tag match those of Revert To,
    // so AppKit's own title for it is the only thing that tells the two apart.
    private static let shareTitle = Bundle(for: NSApplication.self).localizedString(forKey: "Share", value: nil, table: "MenuCommands")

    static func prune(_ menu: NSMenu) {
        for item in menu.items where !item.isSeparatorItem && !isKept(item) {
            menu.removeItem(item)
        }
        removeExtraSeparators(menu)
    }

    private static func isKept(_ item: NSMenuItem) -> Bool {
        if let submenu = item.submenu {
            return item.title == shareTitle
                || submenu.items.contains { $0.action == #selector(NSDocumentController.clearRecentDocuments(_:)) }
        }
        return item.action.map(keptActions.contains) ?? false
    }

    private static func removeExtraSeparators(_ menu: NSMenu) {
        var previousIsSeparator = true
        for item in menu.items {
            if item.isSeparatorItem && previousIsSeparator {
                menu.removeItem(item)
            } else {
                previousIsSeparator = item.isSeparatorItem
            }
        }
        if let last = menu.items.last, last.isSeparatorItem {
            menu.removeItem(last)
        }
    }
}
