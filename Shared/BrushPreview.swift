import Foundation
import BrushkitFFI

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
    static func load(_ url: URL, maxCell: Int) throws -> BrushPreviewSet {
        guard let format = BrushFormat(url: url) else {
            throw BrushPreviewError(message: "Unrecognised brush file extension: \(url.pathExtension)")
        }
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
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
            return BrushEntry(name: String(cString: entry.name), tip: tip)
        }
        return BrushPreviewSet(name: name, entries: entries)
    }
}
