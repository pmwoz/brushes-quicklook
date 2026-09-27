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
    /// Brushes after `entries` that the parser did not reach before the time limit. Never above 0
    /// while `entries` is empty, because `load` throws `timedOut` then.
    let notReached: Int
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
    /// Reads and parses `url` on a background queue. The parser stops at `budget.timeLimit` and
    /// returns the brushes it built by then. Throws when the file is not a brush file, is above
    /// `LoadBudget.maxFileSize`, cannot be read, fails to parse, has no brush built by the time
    /// limit, or runs past it by more than `LoadBudget.grace`. When the second decode of a single
    /// brush fails or runs out of time, the first decode is returned.
    static func load(_ url: URL, budget: LoadBudget) throws -> BrushPreviewSet {
        let format = try BrushFormat(url: url)
        let id = signposter.makeSignpostID()
        let state = signposter.beginInterval("load", id: id, "\(String(describing: format), privacy: .public) maxCell \(budget.cell)")
        defer { signposter.endInterval("load", state) }

        let result = OSAllocatedUnfairLock<Result<BrushPreviewSet, any Error>?>(initialState: nil)
        let semaphore = DispatchSemaphore(value: 0)
        let seconds = budget.timeLimit / .seconds(1)
        let deadline = DispatchTime.now() + seconds
        DispatchQueue.global(qos: .userInitiated).async {
            defer { semaphore.signal() }
            let data: Data
            do {
                data = try readBounded(url, id: id)
            } catch {
                result.withLock { $0 = .failure(error) }
                return
            }
            let firstAvailable: Int? = if case .firstAvailable(let count) = budget.entries { count } else { nil }
            let first = Result {
                let set = try decode(data, format: format, cell: budget.cell, firstAvailable: firstAvailable, deadline: deadline, id: id)
                guard set.notReached > 0 else { return set }
                logger.notice("Stopped at the time limit: \(set.entries.count) built, \(set.notReached) not reached")
                guard !set.entries.isEmpty else { throw BrushPreviewError.timedOut(budget.timeLimit) }
                return set
            }
            result.withLock { $0 = first }
            guard case .all(let singleBrushCell?) = budget.entries, case .success(let set) = first,
                  set.entries.count == 1, set.notReached == 0 else { return }
            let sharperID = signposter.makeSignpostID()
            let sharper = signposter.withIntervalSignpost(
                "load", id: sharperID,
                "\(String(describing: format), privacy: .public) single brush again, maxCell \(singleBrushCell)"
            ) {
                try? decode(data, format: format, cell: singleBrushCell, firstAvailable: nil, deadline: deadline, id: sharperID)
            }
            if let sharper, sharper.notReached == 0 {
                result.withLock { $0 = .success(sharper) }
            }
        }
        if semaphore.wait(timeout: deadline + LoadBudget.grace / .seconds(1)) == .timedOut {
            if let first = result.withLock({ $0 }) {
                return try first.get()
            }
            logger.error("Timed out after \(seconds, format: .fixed(precision: 1)) s: \(String(describing: format), privacy: .public)")
            throw BrushPreviewError.timedOut(budget.timeLimit)
        }
        return try result.withLock { $0! }.get()
    }

    /// Checks the ceiling on the opened file, which is the target of a symbolic link, and again on
    /// the bytes read, so a file that grows after the check cannot pass it either.
    private static func readBounded(_ url: URL, id: OSSignpostID) throws -> Data {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let size = try handle.seekToEnd()
        guard size <= LoadBudget.maxFileSize else {
            throw BrushPreviewError.tooLarge(size: Int(clamping: size), limit: LoadBudget.maxFileSize)
        }
        try handle.seek(toOffset: 0)
        let data = try signposter.withIntervalSignpost("read", id: id, "\(size) bytes") {
            try handle.read(upToCount: LoadBudget.maxFileSize + 1) ?? Data()
        }
        guard data.count <= LoadBudget.maxFileSize else {
            throw BrushPreviewError.tooLarge(size: data.count, limit: LoadBudget.maxFileSize)
        }
        return data
    }

    private static func decode(
        _ data: Data, format: BrushFormat, cell: Int, firstAvailable: Int?, deadline: DispatchTime, id: OSSignpostID
    ) throws -> BrushPreviewSet {
        let left = deadline.uptimeNanoseconds.subtractingReportingOverflow(DispatchTime.now().uptimeNanoseconds)
        let stopAfterMilliseconds = left.overflow ? 0 : UInt32(clamping: left.partialValue / 1_000_000)
        var error: UnsafeMutablePointer<CChar>?
        let set = signposter.withIntervalSignpost("parse", id: id) {
            data.withUnsafeBytes { bytes in
                let base = bytes.bindMemory(to: UInt8.self).baseAddress
                if let firstAvailable {
                    return bqk_preview_first_available(
                        base, bytes.count, format.cValue, UInt32(cell), firstAvailable, stopAfterMilliseconds, &error
                    )
                }
                return bqk_preview(base, bytes.count, format.cValue, UInt32(cell), stopAfterMilliseconds, &error)
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
        return BrushPreviewSet(name: name, entries: entries, notReached: bqk_preview_set_not_reached(set))
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
