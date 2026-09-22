import AppKit
import SwiftUI

enum BrushTipImage {
    static func make(from tip: BrushTip) -> CGImage? {
        guard case let .available(width, height, pixels) = tip,
              width > 0, height > 0 else { return nil }
        let (count, overflow) = width.multipliedReportingOverflow(by: height)
        guard !overflow, pixels.count == count else { return nil }
        var rgba = Data(count: count * 4)
        rgba.withUnsafeMutableBytes { (bytes: UnsafeMutableRawBufferPointer) in
            for (index, coverage) in pixels.enumerated() {
                bytes[index * 4 + 3] = coverage
            }
        }
        guard let provider = CGDataProvider(data: rgba as CFData) else { return nil }
        return CGImage(
            width: width, height: height,
            bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
            provider: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent
        )
    }
}

struct PreviewGrid: View {
    let title: String
    let cells: [BrushPreviewCell]

    init(title: String, set: BrushPreviewSet) {
        self.title = title
        cells = set.entries.map(BrushPreviewCell.init)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.title2.weight(.semibold))
                    .lineLimit(2)
                    .help(title)
                Text("\(cells.count) \(cells.count == 1 ? "brush" : "brushes")")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .padding(20)
            Divider()
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 180, maximum: 240), spacing: 16)], spacing: 16) {
                    ForEach(cells.indices, id: \.self) { index in
                        cells[index]
                    }
                }
                .padding(20)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(nsColor: .windowBackgroundColor))
        .foregroundStyle(.primary)
    }
}

struct BrushPreviewCell: View {
    let entry: BrushEntry
    let image: CGImage?

    init(entry: BrushEntry) {
        self.entry = entry
        image = BrushTipImage.make(from: entry.tip)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Group {
                if let image {
                    Image(decorative: image, scale: 1)
                        .renderingMode(.template)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .padding(16)
                        .frame(height: 150)
                } else {
                    VStack(spacing: 8) {
                        Image(systemName: "photo.badge.exclamationmark")
                            .font(.title2)
                        Text("Preview unavailable")
                            .font(.callout.weight(.medium))
                        Text(unavailableReason)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(12)
                }
            }
            .frame(maxWidth: .infinity)
            .frame(minHeight: 150)
            .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
            .accessibilityHidden(true)

            Text(entry.name)
                .font(.callout.weight(.medium))
                .lineLimit(2, reservesSpace: true)
                .help(entry.name)
            Text(dimensionsText)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(entry.name), \(dimensionsText)\(image == nil ? ", Preview unavailable, \(unavailableReason)" : "")")
    }

    private var dimensionsText: String {
        if let dimensions = entry.sourceDimensions {
            "\(dimensions.width) × \(dimensions.height) px"
        } else {
            "Source size unknown"
        }
    }

    private var unavailableReason: String {
        if case let .unavailable(reason) = entry.tip { reason } else { "Unable to display this tip" }
    }
}
