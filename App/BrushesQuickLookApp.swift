import SwiftUI

@main
struct BrushesQuickLookApp: App {
    static let setupWindowID = "setup"

    @NSApplicationDelegateAdaptor private var appDelegate: AppDelegate

    // CommandGroup(replacing: .newItem) also removes Open and Open Recent on macOS 14.
    private static let unsupportedActions: Set<Selector> = [
        #selector(NSDocumentController.newDocument(_:)),
        #selector(NSDocument.save(_:)),
        #selector(NSDocument.saveAs(_:)),
        #selector(NSDocument.duplicate(_:)),
        #selector(NSDocument.rename(_:)),
        #selector(NSDocument.move(_:)),
        #selector(NSDocument.revertToSaved(_:)),
    ]

    init() {
        // macOS 14 shows an Open panel at launch next to the setup window when this key is unset.
        UserDefaults.standard.register(defaults: ["NSShowAppCentricOpenPanelInsteadOfUntitledFile": false])
        Task {
            let additions = NotificationCenter.default.notifications(named: NSMenu.didAddItemNotification)
            Self.removeUnsupportedItems()
            // SwiftUI re-adds DocumentGroup's document items to the File menu when a document window closes.
            for await _ in additions {
                Self.removeUnsupportedItems()
            }
        }
    }

    private static func removeUnsupportedItems() {
        for menu in NSApp.mainMenu?.items.compactMap(\.submenu) ?? [] {
            for item in menu.items {
                guard let action = item.action, unsupportedActions.contains(action) else { continue }
                menu.removeItem(item)
            }
        }
    }

    var body: some Scene {
        Window("Brushes Quick Look", id: Self.setupWindowID) {
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

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationWillFinishLaunching(_ notification: Notification) {
        let controller = NSDocumentController.shared
        let brushType = BrushDocument.readableContentTypes[0].identifier
        guard let documentClass = controller.documentClass(forType: brushType),
              let documentMetaclass = object_getClass(documentClass)
        else {
            return assertionFailure("SwiftUI's document class not found, so documents read in parallel and titles offer rename")
        }
        // SwiftUI's document class lets NSDocumentController read documents on parallel threads. On macOS 14
        // those threads race on AppKit's document opening session and can crash the app. A brush document
        // reads nothing, so the class is made to read on the main thread instead.
        let never: @convention(block) (AnyObject, NSString?) -> ObjCBool = { _, _ in false }
        replaceMethod(#selector(NSDocument.canConcurrentlyReadDocuments(ofType:)), of: documentMetaclass, with: never)
        // A window title offers rename, move, tags and lock in a popover, and the File menu gains a Revert To
        // submenu, when its document class autosaves in place.
        // Sharing and the File menu's Share item also follow autosave in place, so they are turned back on.
        let no: @convention(block) (AnyObject) -> ObjCBool = { _ in false }
        let yes: @convention(block) (AnyObject) -> ObjCBool = { _ in true }
        replaceMethod(#selector(getter: NSDocument.allowsDocumentSharing), of: documentClass, with: yes)
        replaceMethod(#selector(getter: NSDocumentController.allowsAutomaticShareMenu), of: type(of: controller), with: yes)
        replaceMethod(#selector(getter: NSDocument.autosavesInPlace), of: documentMetaclass, with: no)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // macOS 14 opens the setup window at launch even when the launch opens files. A launch that restores
        // saved windows is also not a default launch, but it arrives as an open-application event.
        guard notification.userInfo?[NSApplication.launchIsDefaultUserInfoKey] as? Bool == false,
              NSAppleEventManager.shared().currentAppleEvent?.eventID != kAEOpenApplication
        else { return }
        NSApp.windows.first { $0.identifier?.rawValue == BrushesQuickLookApp.setupWindowID }?.close()
    }

    private func replaceMethod(_ selector: Selector, of cls: AnyClass, with block: Any) {
        guard let method = class_getInstanceMethod(cls, selector)
        else { return assertionFailure("\(cls) has no \(selector)") }
        class_replaceMethod(cls, selector, imp_implementationWithBlock(block), method_getTypeEncoding(method))
    }
}
