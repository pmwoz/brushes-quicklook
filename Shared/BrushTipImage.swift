import AppKit

enum BrushTipImage {
    /// Wraps the coverage bytes as an 8-bit image mask backed by the tip's own storage,
    /// so no per-pixel expansion happens. A mask paints the current fill colour where the
    /// sample is 0, so the decode array inverts it: 255 = full ink, 0 = transparent.
    static func make(from tip: BrushTip) -> CGImage? {
        guard case let .available(width, height, pixels) = tip,
              width > 0, height > 0 else { return nil }
        let (count, overflow) = width.multipliedReportingOverflow(by: height)
        guard !overflow, pixels.count == count else { return nil }
        guard let provider = CGDataProvider(data: pixels as CFData) else { return nil }
        let decode: [CGFloat] = [1, 0]
        return decode.withUnsafeBufferPointer { decode in
            CGImage(
                maskWidth: width, height: height,
                bitsPerComponent: 8, bitsPerPixel: 8, bytesPerRow: width,
                provider: provider, decode: decode.baseAddress, shouldInterpolate: true
            )
        }
    }
}
