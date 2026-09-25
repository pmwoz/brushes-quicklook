import Foundation
import BrushkitFFI
import os

enum BrushFormat: Sendable {
    case abr, brush, brushset

    init(url: URL) throws {
        switch url.pathExtension.lowercased() {
        case "abr": self = .abr
        case "brush": self = .brush
        case "brushset": self = .brushset
        default: throw BrushPreviewError.unsupportedExtension(url.pathExtension)
        }
    }

    fileprivate var cValue: bqk_format {
        switch self {
        case .abr: BQK_FORMAT_ABR
        case .brush: BQK_FORMAT_BRUSH
        case .brushset: BQK_FORMAT_BRUSHSET
        }
    }
}

struct BrushPreviewSet: Sendable {
    let name: String?
    let entries: [BrushEntry]
}

struct BrushEntry: Sendable {
    let name: String
    let tip: BrushTip
    let sourceDimensions: BrushSourceDimensions?
}

struct BrushSourceDimensions: Sendable, Equatable {
    let width: UInt32
    let height: UInt32

    init?(width: UInt32, height: UInt32) {
        guard width > 0, height > 0 else { return nil }
        self.width = width
        self.height = height
    }
}

enum BrushTip: Sendable {
    /// `pixels` holds `width * height` coverage bytes, one per pixel, 255 = full ink.
    case available(width: Int, height: Int, pixels: Data)
    case unavailable(reason: String)
}

enum BrushPreviewError: LocalizedError, Sendable {
    case unsupportedExtension(String)
    case tooLarge(size: Int, limit: Int)
    case timedOut(TimeInterval)
    /// Carries the parser's own message.
    case damaged(String)

    var errorDescription: String? {
        switch self {
        case .unsupportedExtension(let pathExtension):
            "Unrecognised brush file extension: \(pathExtension)"
        case .tooLarge(let size, let limit):
            "This file is \(Self.bytes(size)). Files above \(Self.bytes(limit)) are not previewed."
        case .timedOut(let timeout):
            "Previewing took longer than \(timeout.formatted()) seconds."
        case .damaged(let message):
            message
        }
    }

    private static func bytes(_ count: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(count), countStyle: .binary)
    }
}

extension BrushPreviewSet {
    /// Files above this many bytes are refused before any byte reaches the parser.
    static let maxFileSize = 512 << 20

    /// Reads and parses `url` on a background queue. Throws when the file is not a brush
    /// file, is above `maxFileSize`, cannot be read, fails to parse, or takes longer than `timeout`.
    static func load(_ url: URL, maxCell: Int, firstAvailable: Int? = nil, timeout: TimeInterval) throws -> BrushPreviewSet {
        let format = try BrushFormat(url: url)
        let fileSize = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize
        if let fileSize, fileSize > maxFileSize {
            throw BrushPreviewError.tooLarge(size: fileSize, limit: maxFileSize)
        }

        let result = OSAllocatedUnfairLock<Result<BrushPreviewSet, any Error>?>(initialState: nil)
        let semaphore = DispatchSemaphore(value: 0)
        let deadline = DispatchTime.now() + timeout
        DispatchQueue.global(qos: .userInitiated).async {
            let parsed = Result { try read(url, format: format, maxCell: maxCell, firstAvailable: firstAvailable) }
            result.withLock { $0 = parsed }
            semaphore.signal()
        }
        guard semaphore.wait(timeout: deadline) == .success else {
            throw BrushPreviewError.timedOut(timeout)
        }
        return try result.withLock { $0! }.get()
    }

    private static func read(_ url: URL, format: BrushFormat, maxCell: Int, firstAvailable: Int?) throws -> BrushPreviewSet {
        let data = try Data(contentsOf: url)
        var error: UnsafeMutablePointer<CChar>?
        let set = data.withUnsafeBytes { bytes in
            let base = bytes.bindMemory(to: UInt8.self).baseAddress
            if let firstAvailable {
                return bqk_preview_first_available(base, bytes.count, format.cValue, UInt32(maxCell), firstAvailable, &error)
            }
            return bqk_preview(base, bytes.count, format.cValue, UInt32(maxCell), &error)
        }
        defer { bqk_string_free(error) }
        guard let set else {
            throw BrushPreviewError.damaged(error.map { String(cString: $0) } ?? "Unable to preview this brush file.")
        }
        defer { bqk_preview_set_free(set) }

        let name = bqk_preview_set_name(set).map { String(cString: $0) }
        let entries = (0..<bqk_preview_set_count(set)).map { index in
            let entry = bqk_preview_set_entry(set, index)
            return BrushEntry(copying: entry)
        }
        return BrushPreviewSet(name: name, entries: entries)
    }
}

extension BrushEntry {
    init(copying entry: bqk_entry) {
        let tip: BrushTip
        if let pixels = entry.pixels {
            let width = Int(entry.width)
            let height = Int(entry.height)
            tip = .available(
                width: width,
                height: height,
                pixels: Data(bytes: pixels, count: width * height)
            )
        } else {
            tip = .unavailable(reason: entry.unavailable_reason.map { String(cString: $0) } ?? "Preview unavailable")
        }

        self.init(
            name: String(cString: entry.name),
            tip: tip,
            sourceDimensions: BrushSourceDimensions(width: entry.source_width, height: entry.source_height)
        )
    }
}
