import AppKit
import XCTest

final class ThumbnailTests: XCTestCase {
    private let size = CGSize(width: 128, height: 128)
    private let unavailable = BrushTip.unavailable(reason: "No shape")

    func testNoUsableTipsShowsNoTipsState() {
        for tips: [BrushTip] in [[], [unavailable], [unavailable, .available(width: 2, height: 2, pixels: Data([255]))]] {
            let thumbnail = BrushThumbnail(format: .abr, tips: tips, size: size)
            guard case .empty(.noTips) = thumbnail.layout else { return XCTFail("Expected the no-tips state") }
        }
    }

    func testOneToThreeUsableTipsShowsFirstTip() throws {
        for count in 1...3 {
            let tips = [unavailable] + (1...count).map { tip(UInt8($0)) }
            let thumbnail = BrushThumbnail(format: .brush, tips: tips, size: size)
            guard case let .single(image) = thumbnail.layout else { return XCTFail("Expected a single tip for \(count) tips") }
            XCTAssertEqual(try pixels(image), Data([1]))
        }
    }

    func testFourTipsBelow64PointsShowsFirstTip() throws {
        let thumbnail = BrushThumbnail(format: .abr, tips: (1...4).map { tip(UInt8($0)) }, size: CGSize(width: 63, height: 63))
        guard case let .single(image) = thumbnail.layout else { return XCTFail("Expected a single tip for a small icon") }
        XCTAssertEqual(try pixels(image), Data([1]))
    }

    func testTipCountIsOneBelow64PointsOnTheShorterSide() {
        XCTAssertEqual(BrushThumbnail.tipCount(for: CGSize(width: 16, height: 16)), 1)
        XCTAssertEqual(BrushThumbnail.tipCount(for: CGSize(width: 63, height: 63)), 1)
        XCTAssertEqual(BrushThumbnail.tipCount(for: CGSize(width: 128, height: 32)), 1)
        XCTAssertEqual(BrushThumbnail.tipCount(for: CGSize(width: 64, height: 64)), 4)
    }

    func testGridUsesFirstFourUsableTipsInOrderAt64Points() throws {
        let tips = [unavailable, tip(1), tip(2), unavailable,
                    .available(width: 0, height: 1, pixels: Data()), tip(3), tip(4), tip(5)]
        let thumbnail = BrushThumbnail(format: .brushset, tips: tips, size: CGSize(width: 64, height: 64))
        guard case let .grid(images) = thumbnail.layout else { return XCTFail("Expected a grid at 64 points") }
        XCTAssertEqual(try images.map(pixels), [Data([1]), Data([2]), Data([3]), Data([4])])
        let narrow = BrushThumbnail(format: .brushset, tips: tips, size: CGSize(width: 128, height: 32))
        guard case .single = narrow.layout else { return XCTFail("The drawn square follows the shorter side") }
    }

    func testLoadRootBrushShowsSingleTip() throws {
        let file = try copyFixture("root_brush", extension: "brush")
        defer { try? FileManager.default.removeItem(at: file) }

        let thumbnail = try BrushThumbnail.load(file, maximumSize: CGSize(width: 3.25, height: 2), scale: 2)
        XCTAssertEqual(thumbnail.format, .brush)
        guard case let .single(image) = thumbnail.layout else { return XCTFail("Expected the fixture's tip") }
        XCTAssertEqual(image.width, 7, "Decode size uses the longer side in pixels")
        XCTAssertEqual(image.height, 4)
    }

    func testZeroAreaTipDoesNotTakeTheSingleTipSlot() throws {
        let file = try copyFixture("zero_area_tip", extension: "abr")
        defer { try? FileManager.default.removeItem(at: file) }

        let thumbnail = try BrushThumbnail.load(file, maximumSize: CGSize(width: 32, height: 32), scale: 1)
        guard case let .single(image) = thumbnail.layout else { return XCTFail("Expected the drawable tip after the zero-area one") }
        XCTAssertEqual(image.width, 1)
        XCTAssertEqual(image.height, 1)
    }

    func testParsedFileWithoutDrawableTipShowsNoTipsState() throws {
        let file = try copyFixture("missing_shape", extension: "brush")
        defer { try? FileManager.default.removeItem(at: file) }

        let thumbnail = try BrushThumbnail.load(file, maximumSize: size, scale: 2)
        guard case .empty(.noTips) = thumbnail.layout else { return XCTFail("Expected the no-tips state") }
    }

    func testCorruptAndMissingFilesShowUnreadableState() throws {
        let file = temporaryFile(extension: "abr")
        try Data("Not a brush file".utf8).write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        for url in [file, temporaryFile(extension: "abr")] {
            let thumbnail = try BrushThumbnail.load(url, maximumSize: size, scale: 2)
            XCTAssertEqual(thumbnail.format, .abr)
            guard case .empty(.unreadable) = thumbnail.layout else { return XCTFail("Expected the unreadable state after a load error") }
        }
    }

    func testPillIsFilledWithTheFormatColourAt128Points() throws {
        for (format, expected) in [(BrushFormat.abr, [47, 111, 237, 255]), (.brushset, [233, 105, 44, 255])] {
            let context = try draw(BrushThumbnail(format: format, tips: [], size: size), pixels: 128)
            for (actual, expected) in zip(try pixel(context, x: 64, y: 15), expected) {
                XCTAssertEqual(Int(actual), expected, accuracy: 1, "\(format)")
            }
        }
    }

    func testBelow64PointsAStripReplacesThePill() throws {
        let context = try draw(BrushThumbnail(format: .abr, tips: [], size: CGSize(width: 32, height: 32)), pixels: 64)
        for (actual, expected) in zip(try pixel(context, x: 32, y: 5), [47, 111, 237, 255]) {
            XCTAssertEqual(Int(actual), expected, accuracy: 1)
        }
        XCTAssertEqual(try pixel(context, x: 32, y: 12), [255, 255, 255, 255], "No pill above the strip")
    }

    func testEmptyStatesDrawAGlyphOnTheCard() throws {
        let noTips = BrushThumbnail(format: .abr, tips: [], size: size)
        let unreadable = try BrushThumbnail.load(temporaryFile(extension: "abr"), maximumSize: size, scale: 1)
        for thumbnail in [noTips, unreadable] {
            let context = try draw(thumbnail, pixels: 128)
            // The glyph is centred 42% down the card, around (64, 73) in drawing space.
            let region = try (61..<85).flatMap { y in try (52..<76).map { x in Int(try pixel(context, x: x, y: y)[0]) } }
            XCTAssertLessThan(region.reduce(0, +) / region.count, 245, "\(thumbnail.layout) draws a glyph")
        }
    }

    func testFullInkTipDrawsNearBlackAtCardCentre() throws {
        let context = try draw(BrushThumbnail(format: .brush, tips: [tip(255)], size: size), pixels: 128)
        let centre = try pixel(context, x: 64, y: 64)
        for channel in centre.prefix(3) {
            // Generic gray 0.1 converts to approximately 34 in the sRGB bitmap.
            XCTAssertEqual(Int(channel), 34, accuracy: 2)
        }
        XCTAssertEqual(centre[3], 255)
    }

    func testGridDrawsInRowsFromTheTop() throws {
        let thumbnail = BrushThumbnail(format: .abr, tips: [tip(255), tip(170), tip(85), tip(0)], size: size)
        let context = try draw(thumbnail, pixels: 128)
        let centres = [(x: 39, y: 97), (x: 89, y: 97), (x: 39, y: 54), (x: 89, y: 54)]
        let shades = try centres.map { try pixel(context, x: $0.x, y: $0.y)[0] }
        XCTAssertLessThan(shades[0], shades[1])
        XCTAssertLessThan(shades[1], shades[2])
        XCTAssertLessThan(shades[2], shades[3])
        XCTAssertEqual(shades[3], 255)
    }

    private func tip(_ coverage: UInt8) -> BrushTip {
        .available(width: 1, height: 1, pixels: Data([coverage]))
    }

    private func pixels(_ image: CGImage) throws -> Data {
        try XCTUnwrap(image.dataProvider?.data) as Data
    }

    private func temporaryFile(extension fileExtension: String) -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathExtension(fileExtension)
    }

    private func copyFixture(_ name: String, extension fileExtension: String) throws -> URL {
        let source = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: nil))
        let file = temporaryFile(extension: fileExtension)
        try FileManager.default.copyItem(at: source, to: file)
        return file
    }

    private func draw(_ thumbnail: BrushThumbnail, pixels side: Int) throws -> CGContext {
        let space = try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB))
        let context = try XCTUnwrap(CGContext(
            data: nil, width: side, height: side, bitsPerComponent: 8, bytesPerRow: side * 4,
            space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ))
        thumbnail.draw(in: context, size: CGSize(width: side, height: side))
        return context
    }

    private func pixel(_ context: CGContext, x: Int, y: Int) throws -> [UInt8] {
        let data = try XCTUnwrap(context.data).assumingMemoryBound(to: UInt8.self)
        // Bitmap rows start at the top, while the drawing space starts at the bottom.
        let offset = (context.height - 1 - y) * context.bytesPerRow + x * 4
        return Array(UnsafeBufferPointer(start: data + offset, count: 4))
    }
}
