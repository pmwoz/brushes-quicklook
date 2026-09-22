import Foundation
import BrushkitFFI
import os

enum BrushFormat: Sendable {
    case abr, brush, brushset

    init?(url: URL) {
        switch url.pathExtension.lowercased() {
        case "abr": self = .abr
        case "brush": self = .brush
        case "brushset": self = .brushset
        default: return nil
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
    case available(width: Int, height: Int, pixels: [UInt8])
    case unavailable(reason: String)
}

struct BrushPreviewError: LocalizedError, Sendable {
    let message: String
    var errorDescription: String? { message }
}

extension BrushPreviewSet {
    /// Files above this many bytes are refused before any byte reaches the parser.
    static let maxFileSize = 512 << 20

    /// Reads and parses `url` on a background queue. Throws when the file is not a brush
    /// file, is above `maxFileSize`, cannot be read, fails to parse, or takes longer than `timeout`.
    static func load(_ url: URL, maxCell: Int, timeout: TimeInterval) throws -> BrushPreviewSet {
        guard let format = BrushFormat(url: url) else {
            throw BrushPreviewError(message: "Unrecognised brush file extension: \(url.pathExtension)")
        }
        let fileSize = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize
        if let fileSize, fileSize > maxFileSize {
            let size = ByteCountFormatter.string(fromByteCount: Int64(fileSize), countStyle: .binary)
            let limit = ByteCountFormatter.string(fromByteCount: Int64(maxFileSize), countStyle: .binary)
            throw BrushPreviewError(message: "This file is \(size). Files above \(limit) are not previewed.")
        }

        let result = OSAllocatedUnfairLock<Result<BrushPreviewSet, any Error>?>(initialState: nil)
        let semaphore = DispatchSemaphore(value: 0)
        let deadline = DispatchTime.now() + timeout
        DispatchQueue.global(qos: .userInitiated).async {
            let parsed = Result { try read(url, format: format, maxCell: maxCell) }
            result.withLock { $0 = parsed }
            semaphore.signal()
        }
        guard semaphore.wait(timeout: deadline) == .success else {
            throw BrushPreviewError(message: "Previewing took longer than \(timeout.formatted()) seconds.")
        }
        return try result.withLock { $0! }.get()
    }

    private static func read(_ url: URL, format: BrushFormat, maxCell: Int) throws -> BrushPreviewSet {
        let data = try Data(contentsOf: url)
        var error: UnsafeMutablePointer<CChar>?
        let set = data.withUnsafeBytes { bytes in
            bqk_preview(bytes.bindMemory(to: UInt8.self).baseAddress, bytes.count, format.cValue, UInt32(maxCell), &error)
        }
        defer { bqk_string_free(error) }
        guard let set else {
            throw BrushPreviewError(message: error.map { String(cString: $0) } ?? "Unable to preview this brush file.")
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
                pixels: Array(UnsafeBufferPointer(start: pixels, count: width * height))
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
