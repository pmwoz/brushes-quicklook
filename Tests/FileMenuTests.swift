import AppKit
import XCTest

final class FileMenuTests: XCTestCase {
    // A test run gets AppKit's strings in the system language, and the English-only app gets English.
    private static let share = Bundle(for: NSApplication.self).localizedString(forKey: "Share", value: nil, table: "MenuCommands")
    private let viewerCommands = ["Open…", "Open Recent", "-", "Close", "Close All", "-", FileMenuTests.share]

    @MainActor
    func testKeepsOnlyViewerCommandsWhenTheDocumentAutosavesInPlace() {
        let menu = documentGroupFileMenu(autosavesInPlace: true)
        FileMenu.prune(menu)
        XCTAssertEqual(titles(menu), viewerCommands)
    }

    @MainActor
    func testKeepsOnlyViewerCommandsWhenTheDocumentDoesNotAutosaveInPlace() {
        let menu = documentGroupFileMenu(autosavesInPlace: false)
        FileMenu.prune(menu)
        XCTAssertEqual(titles(menu), viewerCommands)
    }

    @MainActor
    func testRemovesACommandALaterMacOSAdds() {
        for autosavesInPlace in [true, false] {
            let menu = documentGroupFileMenu(autosavesInPlace: autosavesInPlace)
            menu.addItem(item("Export…", "exportDocument:"))
            FileMenu.prune(menu)
            XCTAssertEqual(titles(menu), viewerCommands, "autosavesInPlace \(autosavesInPlace)")
        }
    }

    @MainActor
    private func documentGroupFileMenu(autosavesInPlace: Bool) -> NSMenu {
        let hiddenSeparator = NSMenuItem.separator()
        hiddenSeparator.isHidden = true
        let menu = NSMenu(title: "File")
        menu.items = [
            item("New", "newDocument:"),
            hiddenSeparator,
            item("Open…", "openDocument:"),
            submenu("Open Recent", [item("Clear Menu", "clearRecentDocuments:")]),
            .separator(),
            item("Close", "performClose:"),
            item("Close All", "closeAll:"),
            item("Save", "saveDocument:"),
            item("Save As…", "saveDocumentAs:"),
            item("Duplicate", "duplicateDocument:"),
            item("Rename…", "renameDocument:"),
            item("Move To…", "moveDocument:"),
            item("Revert To Saved", "revertDocumentToSaved:"),
        ]
        if autosavesInPlace {
            menu.addItem(submenu("Revert To", []))
        }
        menu.addItem(.separator())
        menu.addItem(submenu(Self.share, []))
        menu.addItem(.separator())
        return menu
    }

    @MainActor
    private func item(_ title: String, _ action: String) -> NSMenuItem {
        NSMenuItem(title: title, action: Selector(action), keyEquivalent: "")
    }

    @MainActor
    private func submenu(_ title: String, _ items: [NSMenuItem]) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.submenu = NSMenu(title: title)
        item.submenu?.items = items
        return item
    }

    @MainActor
    private func titles(_ menu: NSMenu) -> [String] {
        menu.items.map { $0.isSeparatorItem ? "-" : $0.title }
    }
}
