import AppKit
import XCTest

final class ThumbnailTests: XCTestCase {
    private let size = CGSize(width: 128, height: 128)
    private let unavailable = BrushTip.unavailable(reason: "No shape")

    func testNoUsableTipsShowsOnlyBadge() {
        for tips: [BrushTip] in [[], [unavailable], [unavailable, .available(width: 2, height: 2, pixels: Data([255]))]] {
            let thumbnail = BrushThumbnail(badge: "ABR", tips: tips, size: size)
            guard case .badgeOnly = thumbnail.layout else { return XCTFail("Expected only a badge") }
        }
    }

    func testOneToThreeUsableTipsShowsFirstTip() throws {
        for count in 1...3 {
            let tips = [unavailable] + (1...count).map { tip(UInt8($0)) }
            let thumbnail = BrushThumbnail(badge: "BRUSH", tips: tips, size: size)
            guard case let .single(image) = thumbnail.layout else { return XCTFail("Expected a single tip for \(count) tips") }
            XCTAssertEqual(try pixels(image), Data([1]))
        }
    }

    func testFourTipsBelow64PointsShowsFirstTip() throws {
        let thumbnail = BrushThumbnail(badge: "ABR", tips: (1...4).map { tip(UInt8($0)) }, size: CGSize(width: 63, height: 63))
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
        let thumbnail = BrushThumbnail(badge: "BRUSHSET", tips: tips, size: CGSize(width: 64, height: 64))
        guard case let .grid(images) = thumbnail.layout else { return XCTFail("Expected a grid at 64 points") }
        XCTAssertEqual(try images.map(pixels), [Data([1]), Data([2]), Data([3]), Data([4])])
        let narrow = BrushThumbnail(badge: "BRUSHSET", tips: tips, size: CGSize(width: 128, height: 32))
        guard case .single = narrow.layout else { return XCTFail("The drawn square follows the shorter side") }
    }

    func testLoadRootBrushShowsSingleTip() throws {
        let source = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "root_brush", withExtension: nil))
        let file = temporaryFile(extension: "brush")
        try FileManager.default.copyItem(at: source, to: file)
        defer { try? FileManager.default.removeItem(at: file) }

        let thumbnail = BrushThumbnail.load(file, maximumSize: CGSize(width: 3.25, height: 2), scale: 2)
        XCTAssertEqual(thumbnail.badge, "BRUSH")
        guard case let .single(image) = thumbnail.layout else { return XCTFail("Expected the fixture's tip") }
        XCTAssertEqual(image.width, 7, "Decode size uses the longer side in pixels")
        XCTAssertEqual(image.height, 4)
    }

    func testCorruptAndMissingFilesShowOnlyFormatBadge() throws {
        let file = temporaryFile(extension: "abr")
        try Data("Not a brush file".utf8).write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        for url in [file, temporaryFile(extension: "abr")] {
            let thumbnail = BrushThumbnail.load(url, maximumSize: size, scale: 2)
            XCTAssertEqual(thumbnail.badge, "ABR")
            guard case .badgeOnly = thumbnail.layout else { return XCTFail("Expected a badge after a load error") }
        }
    }

    func testBadgeOnlyDrawsWhiteCardAndBluePill() throws {
        let context = try draw(BrushThumbnail(badge: "ABR", tips: [], size: size))
        XCTAssertEqual(try pixel(context, x: 64, y: 64), [255, 255, 255, 255])
        let blue = try pixel(context, x: 64, y: 15)
        for (actual, expected) in zip(blue, [51, 89, 230, 255]) {
            XCTAssertEqual(Int(actual), expected, accuracy: 1)
        }
    }

    func testFullInkTipDrawsNearBlackAtCardCentre() throws {
        let context = try draw(BrushThumbnail(badge: "BRUSH", tips: [tip(255)], size: size))
        let centre = try pixel(context, x: 64, y: 64)
        for channel in centre.prefix(3) {
            // Generic gray 0.1 converts to approximately 34 in the sRGB bitmap.
            XCTAssertEqual(Int(channel), 34, accuracy: 2)
        }
        XCTAssertEqual(centre[3], 255)
    }

    func testGridDrawsInRowsFromTheTop() throws {
        let thumbnail = BrushThumbnail(badge: "ABR", tips: [tip(255), tip(170), tip(85), tip(0)], size: size)
        let context = try draw(thumbnail)
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

    private func draw(_ thumbnail: BrushThumbnail) throws -> CGContext {
        let space = try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB))
        let context = try XCTUnwrap(CGContext(
            data: nil, width: 128, height: 128, bitsPerComponent: 8, bytesPerRow: 128 * 4,
            space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ))
        thumbnail.draw(in: context, size: size)
        return context
    }

    private func pixel(_ context: CGContext, x: Int, y: Int) throws -> [UInt8] {
        let data = try XCTUnwrap(context.data).assumingMemoryBound(to: UInt8.self)
        // Bitmap rows start at the top, while the drawing space starts at the bottom.
        let offset = (context.height - 1 - y) * context.bytesPerRow + x * 4
        return Array(UnsafeBufferPointer(start: data + offset, count: 4))
    }
}
