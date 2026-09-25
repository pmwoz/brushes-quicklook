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
        XCTAssertEqual(pixels, Data(repeating: 200, count: 32))
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

    func testFirstAvailableLimitsEntriesInSetOrder() throws {
        let file = try copyFixture("ordered_set", extension: "brushset")
        defer { try? FileManager.default.removeItem(at: file) }
        let full = try BrushPreviewSet.load(file, maxCell: 8, timeout: 10)
        XCTAssertEqual(full.entries.count, 2)
        let first = try BrushPreviewSet.load(file, maxCell: 8, firstAvailable: 1, timeout: 10)
        XCTAssertEqual(first.entries.map(\.name), [full.entries[0].name])
        guard case .available = first.entries.first?.tip else { return XCTFail("Expected an available tip") }
    }

    func testPartialSourcePairIsUnknown() {
        "Brush".withCString { name in
            let entry = bqk_entry(name: name, width: 0, height: 0, pixels: nil, unavailable_reason: nil, source_width: 320, source_height: 0)
            XCTAssertNil(BrushEntry(copying: entry).sourceDimensions)
        }
    }

    func testCoverageBecomesOwnedMaskTintedByFillWithFullInkAt255() throws {
        var source = Data([0, 128, 255])
        let image = try XCTUnwrap(BrushTipImage.make(from: .available(width: 3, height: 1, pixels: source)))

        XCTAssertTrue(image.isMask)
        XCTAssertEqual(image.bitsPerComponent, 8)
        XCTAssertEqual(image.bitsPerPixel, 8)
        XCTAssertEqual(image.bytesPerRow, 3)
        XCTAssertEqual(try XCTUnwrap(image.dataProvider?.data) as Data, Data([0, 128, 255]))

        let black = try draw(image, fill: CGColor(red: 0, green: 0, blue: 0, alpha: 1))
        XCTAssertEqual([black[3], black[7], black[11]], [0, 128, 255])
        XCTAssertEqual(Array(black[8..<11]), [0, 0, 0])
        let white = try draw(image, fill: CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        XCTAssertEqual([white[3], white[7], white[11]], [0, 128, 255])
        XCTAssertEqual(Array(white[8..<11]), [255, 255, 255])
        XCTAssertEqual(Array(white[4..<7]), [128, 128, 128], "Premultiplied white at half coverage")

        source[0] = 255
        source = Data()
        XCTAssertEqual(source.count, 0)
        let redrawn = try draw(image, fill: CGColor(red: 0, green: 0, blue: 0, alpha: 1))
        XCTAssertEqual([redrawn[3], redrawn[7], redrawn[11]], [0, 128, 255])
        let scoped = try XCTUnwrap(BrushTipImage.make(from: .available(width: 1, height: 1, pixels: Data([255]))))
        XCTAssertEqual(try draw(scoped, fill: CGColor(red: 0, green: 0, blue: 0, alpha: 1)), [0, 0, 0, 255])
    }

    private func draw(_ image: CGImage, fill: CGColor) throws -> [UInt8] {
        let width = image.width
        let context = try XCTUnwrap(CGContext(data: nil, width: width, height: 1, bitsPerComponent: 8, bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.setFillColor(fill)
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: 1))
        let bytes = try XCTUnwrap(context.data).bindMemory(to: UInt8.self, capacity: width * 4)
        return Array(UnsafeBufferPointer(start: bytes, count: width * 4))
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
            BrushEntry(name: "Same name", tip: .available(width: 1, height: 1, pixels: Data([255])), sourceDimensions: nil),
            BrushEntry(name: "Same name", tip: .unavailable(reason: "no Shape.png"), sourceDimensions: nil),
        ])
        controller.finishPreview(current, result: .success(PreviewGrid(fileName: "current.brushset", format: .brushset, set: set)))
        controller.finishPreview(old, result: .success(PreviewGrid(fileName: "old.brush", format: .brush, set: BrushPreviewSet(name: "Stale", entries: []))))
        controller.finishPreview(current, result: .failure(BrushPreviewError(message: "Late")))
        XCTAssertEqual(newCompletions.count, 1)
        XCTAssertNil(newCompletions[0])
        XCTAssertEqual(oldCompletions.count, 1)
        XCTAssertTrue(controller.view.subviews.contains { $0 === controller.preview })
        XCTAssertEqual(controller.preview?.rootView.setName, "Current set")
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
        XCTAssertEqual(hosted.rootView.fileName, file.lastPathComponent)
        XCTAssertEqual(hosted.rootView.format, .brush)
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
        controller.finishPreview(id, result: .failure(BrushPreviewError(message: "Broken brush")))
        controller.finishPreview(id, result: .success(PreviewGrid(fileName: "bad.abr", format: .abr, set: BrushPreviewSet(name: nil, entries: []))))
        XCTAssertEqual(completions.count, 1)
        XCTAssertEqual((completions[0] as NSError?)?.userInfo[NSLocalizedDescriptionKey] as? String, "Broken brush")
        XCTAssertNil(controller.preview)
    }

    func testCountsNameBrushesAndThoseWithoutPreview() {
        XCTAssertEqual(PreviewGrid.countsText(brushes: 1, unavailable: 0), "1 brush")
        XCTAssertEqual(PreviewGrid.countsText(brushes: 26, unavailable: 3), "26 brushes · 3 without preview")
        XCTAssertEqual(PreviewGrid.countsText(brushes: 16, unavailable: 16), "16 brushes · none can be previewed yet")
    }

    private func copyFixture(_ name: String, extension fileExtension: String = "brush") throws -> URL {
        let source = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: nil))
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathExtension(fileExtension)
        try FileManager.default.copyItem(at: source, to: file)
        return file
    }

    private func loadFixture(_ name: String, maxCell: Int = 8) throws -> BrushPreviewSet {
        let file = try copyFixture(name)
        defer { try? FileManager.default.removeItem(at: file) }
        return try BrushPreviewSet.load(file, maxCell: maxCell, timeout: 10)
    }
}
