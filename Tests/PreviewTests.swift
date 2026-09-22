import AppKit
import BrushkitFFI
import XCTest

final class PreviewTests: XCTestCase {
    func testBridgeCopiesOriginalDimensionsSeparatelyFromPixels() throws {
        let set = try loadFixture("root_brush", maxCell: 8)
        XCTAssertEqual(set.entries.count, 1)
        let entry = try XCTUnwrap(set.entries.first)
        XCTAssertEqual(entry.name, "A")
        XCTAssertEqual(entry.sourceDimensions, BrushSourceDimensions(width: 16, height: 8))
        guard case let .available(width, height, pixels) = entry.tip else {
            return XCTFail("Expected available pixels after the Rust set was freed")
        }
        XCTAssertEqual(width, 8)
        XCTAssertEqual(height, 4)
        XCTAssertEqual(pixels, [UInt8](repeating: 200, count: 32))
    }

    func testUnavailableBridgeEntriesKeepOnlyKnownDimensions() throws {
        let missing = try XCTUnwrap(loadFixture("missing_shape").entries.first)
        XCTAssertNil(missing.sourceDimensions)
        guard case .unavailable = missing.tip else { return XCTFail("Expected a placeholder") }
        let large = try XCTUnwrap(loadFixture("oversized_png").entries.first)
        XCTAssertEqual(large.sourceDimensions, BrushSourceDimensions(width: 60000, height: 60000))
        guard case let .unavailable(reason) = large.tip else { return XCTFail("Expected a placeholder") }
        XCTAssertTrue(reason.contains("too large"))
    }

    func testPartialSourcePairIsUnknown() {
        "Brush".withCString { name in
            let entry = bqk_entry(name: name, width: 0, height: 0, pixels: nil, unavailable_reason: nil, source_width: 320, source_height: 0)
            XCTAssertNil(BrushEntry(copying: entry).sourceDimensions)
        }
    }

    func testCoverageBecomesOwnedAlphaWithFullInkAt255() throws {
        let image = try XCTUnwrap(BrushTipImage.make(from: .available(width: 3, height: 1, pixels: [0, 128, 255])))
        let context = try XCTUnwrap(CGContext(data: nil, width: 3, height: 1, bitsPerComponent: 8, bytesPerRow: 12, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.draw(image, in: CGRect(x: 0, y: 0, width: 3, height: 1))
        let pixels = try XCTUnwrap(context.data).bindMemory(to: UInt8.self, capacity: 12)
        XCTAssertEqual([pixels[3], pixels[7], pixels[11]], [0, 128, 255])
        XCTAssertEqual([pixels[8], pixels[9], pixels[10]], [0, 0, 0])
    }

    @MainActor
    func testSupersededRequestCompletesOnceAndCannotReplaceNewPreview() {
        let controller = PreviewViewController()
        var oldCompletions: [Error?] = []
        var newCompletions: [Error?] = []
        let old = controller.beginPreview { oldCompletions.append($0) }
        let current = controller.beginPreview { newCompletions.append($0) }
        XCTAssertEqual(oldCompletions.count, 1)
        XCTAssertEqual((oldCompletions[0] as NSError?)?.code, NSUserCancelledError)
        XCTAssertNil(controller.preview)
        let set = BrushPreviewSet(name: "Current set", entries: [
            BrushEntry(name: "Same name", tip: .available(width: 1, height: 1, pixels: [255]), sourceDimensions: nil),
            BrushEntry(name: "Same name", tip: .unavailable(reason: "no Shape.png"), sourceDimensions: nil),
        ])
        controller.finishPreview(current, result: .success(set), fileName: "current.brushset")
        controller.finishPreview(old, result: .success(BrushPreviewSet(name: "Stale", entries: [])), fileName: "old.brush")
        controller.finishPreview(current, result: .failure(BrushPreviewError(message: "Late")), fileName: "current.brushset")
        XCTAssertEqual(newCompletions.count, 1)
        XCTAssertNil(newCompletions[0])
        XCTAssertEqual(oldCompletions.count, 1)
        XCTAssertTrue(controller.view.subviews.contains { $0 === controller.preview })
        XCTAssertEqual(controller.preview?.rootView.title, "Current set")
        XCTAssertEqual(controller.preview?.rootView.cells.count, 2)
        XCTAssertNotNil(controller.preview?.rootView.cells[0].image)
        XCTAssertNil(controller.preview?.rootView.cells[1].image)
        _ = controller.beginPreview { _ in }
        XCTAssertNil(controller.preview, "Changing files clears the previous content")
    }

    @MainActor
    func testPreparePreviewLoadsAndInstallsHostedGrid() async throws {
        let file = try copyFixture("root_brush")
        defer { try? FileManager.default.removeItem(at: file) }
        let controller = PreviewViewController()
        let completed = expectation(description: "Quick Look preparation completed")
        var completions: [Error?] = []
        controller.preparePreviewOfFile(at: file) { error in
            completions.append(error)
            completed.fulfill()
        }
        let result = await XCTWaiter.fulfillment(of: [completed], timeout: 5)
        XCTAssertEqual(result, .completed)
        XCTAssertEqual(completions.count, 1)
        XCTAssertNil(completions.first ?? nil)
        let hosted = try XCTUnwrap(controller.preview)
        XCTAssertTrue(controller.view.subviews.contains { $0 === hosted })
        XCTAssertEqual(hosted.rootView.title, file.lastPathComponent)
        XCTAssertEqual(hosted.rootView.cells.count, 1)
        let cell = try XCTUnwrap(hosted.rootView.cells.first)
        XCTAssertEqual(cell.name, "A")
        XCTAssertEqual(cell.sourceDimensions, BrushSourceDimensions(width: 16, height: 8))
        XCTAssertNotNil(cell.image)
    }

    @MainActor
    func testFailureCompletesOnceWithQuickLookDescription() {
        let controller = PreviewViewController()
        var completions: [Error?] = []
        let id = controller.beginPreview { completions.append($0) }
        controller.finishPreview(id, result: .failure(BrushPreviewError(message: "Broken brush")), fileName: "bad.abr")
        controller.finishPreview(id, result: .success(BrushPreviewSet(name: nil, entries: [])), fileName: "bad.abr")
        XCTAssertEqual(completions.count, 1)
        XCTAssertEqual((completions[0] as NSError?)?.userInfo[NSLocalizedDescriptionKey] as? String, "Broken brush")
        XCTAssertNil(controller.preview)
    }

    private func copyFixture(_ name: String) throws -> URL {
        let source = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: nil))
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathExtension("brush")
        try FileManager.default.copyItem(at: source, to: file)
        return file
    }

    private func loadFixture(_ name: String, maxCell: Int = 8) throws -> BrushPreviewSet {
        let file = try copyFixture(name)
        defer { try? FileManager.default.removeItem(at: file) }
        return try BrushPreviewSet.load(file, maxCell: maxCell, timeout: 10)
    }
}
