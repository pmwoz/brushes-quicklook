import Foundation
import BrushkitFFI
import os

private let logger = Logger(subsystem: "pl.esdesign.brushesquicklook", category: "load")
private let signposter = OSSignposter(logger: logger)

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
    case timedOut(Duration)
    /// Carries the parser's own message.
    case damaged(String)

    var errorDescription: String? {
        switch self {
        case .unsupportedExtension(let pathExtension):
            "Unrecognised brush file extension: \(pathExtension)"
        case .tooLarge(let size, let limit):
            "This file is \(Self.bytes(size)). Files above \(Self.bytes(limit)) are not previewed."
        case .timedOut(let timeLimit):
            "Previewing took longer than \((timeLimit / .seconds(1)).formatted()) seconds."
        case .damaged(let message):
            message
        }
    }

    private static func bytes(_ count: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(count), countStyle: .binary)
    }
}

extension BrushPreviewSet {
    /// Reads and parses `url` on a background queue. Throws when the file is not a brush file,
    /// is above `LoadBudget.maxFileSize`, cannot be read, fails to parse, or takes longer than
    /// `budget.timeLimit`. When the second decode of a single brush fails or runs out of time,
    /// the first decode is returned.
    static func load(_ url: URL, budget: LoadBudget) throws -> BrushPreviewSet {
        let format = try BrushFormat(url: url)
        let fileSize = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize
        if let fileSize, fileSize > LoadBudget.maxFileSize {
            throw BrushPreviewError.tooLarge(size: fileSize, limit: LoadBudget.maxFileSize)
        }
        let id = signposter.makeSignpostID()
        let state = signposter.beginInterval(
            "load", id: id,
            "\(String(describing: format), privacy: .public) \(fileSize ?? 0) bytes, maxCell \(budget.cell)"
        )
        defer { signposter.endInterval("load", state) }

        let result = OSAllocatedUnfairLock<Result<BrushPreviewSet, any Error>?>(initialState: nil)
        let semaphore = DispatchSemaphore(value: 0)
        let seconds = budget.timeLimit / .seconds(1)
        let deadline = DispatchTime.now() + seconds
        DispatchQueue.global(qos: .userInitiated).async {
            defer { semaphore.signal() }
            let data: Data
            do {
                data = try signposter.withIntervalSignpost("read", id: id) { try Data(contentsOf: url) }
            } catch {
                result.withLock { $0 = .failure(error) }
                return
            }
            let firstAvailable: Int? = if case .firstAvailable(let count) = budget.entries { count } else { nil }
            let first = Result { try decode(data, format: format, cell: budget.cell, firstAvailable: firstAvailable, id: id) }
            result.withLock { $0 = first }
            guard case .all(let singleBrushCell?) = budget.entries, case .success(let set) = first, set.entries.count == 1 else { return }
            let sharperID = signposter.makeSignpostID()
            let sharper = signposter.withIntervalSignpost(
                "load", id: sharperID,
                "\(String(describing: format), privacy: .public) single brush again, maxCell \(singleBrushCell)"
            ) {
                try? decode(data, format: format, cell: singleBrushCell, firstAvailable: nil, id: sharperID)
            }
            if let sharper {
                result.withLock { $0 = .success(sharper) }
            }
        }
        if semaphore.wait(timeout: deadline) == .timedOut {
            if let first = result.withLock({ $0 }) {
                return try first.get()
            }
            logger.error("Timed out after \(seconds, format: .fixed(precision: 1)) s: \(String(describing: format), privacy: .public) \(fileSize ?? 0) bytes")
            throw BrushPreviewError.timedOut(budget.timeLimit)
        }
        return try result.withLock { $0! }.get()
    }

    private static func decode(
        _ data: Data, format: BrushFormat, cell: Int, firstAvailable: Int?, id: OSSignpostID
    ) throws -> BrushPreviewSet {
        var error: UnsafeMutablePointer<CChar>?
        let set = signposter.withIntervalSignpost("parse", id: id) {
            data.withUnsafeBytes { bytes in
                let base = bytes.bindMemory(to: UInt8.self).baseAddress
                if let firstAvailable {
                    return bqk_preview_first_available(base, bytes.count, format.cValue, UInt32(cell), firstAvailable, &error)
                }
                return bqk_preview(base, bytes.count, format.cValue, UInt32(cell), &error)
            }
        }
        defer { bqk_string_free(error) }
        guard let set else {
            throw BrushPreviewError.damaged(error.map { String(cString: $0) } ?? "Unable to preview this brush file.")
        }
        defer { bqk_preview_set_free(set) }

        let name = bqk_preview_set_name(set).map { String(cString: $0) }
        let entries = signposter.withIntervalSignpost("tips", id: id) {
            (0..<bqk_preview_set_count(set)).map { index in
                let entry = bqk_preview_set_entry(set, index)
                return BrushEntry(copying: entry)
            }
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
