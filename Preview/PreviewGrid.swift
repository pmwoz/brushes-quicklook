import AppKit
import SwiftUI

struct PreviewGrid: View {
    let fileName: String
    let format: BrushFormat
    let setName: String?
    let cells: [BrushPreviewCell]

    init(fileName: String, format: BrushFormat, set: BrushPreviewSet) {
        self.fileName = fileName
        self.format = format
        setName = set.name
        cells = set.entries.map(BrushPreviewCell.init)
    }

    nonisolated static func countsText(brushes: Int, unavailable: Int) -> String {
        let total = "\(brushes) \(brushes == 1 ? "brush" : "brushes")"
        if unavailable == 0 { return total }
        if unavailable == brushes { return "\(total) · none can be previewed yet" }
        return "\(total) · \(unavailable) without preview"
    }

    var body: some View {
        Group {
            if cells.count == 1, let cell = cells.first {
                single(cell)
            } else {
                grid
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(nsColor: .windowBackgroundColor))
        .foregroundStyle(.primary)
    }

    private var grid: some View {
        let named = setName.map { $0 != (fileName as NSString).deletingPathExtension } ?? false
        let counts = Self.countsText(brushes: cells.count, unavailable: cells.filter { $0.image == nil }.count)
        let title = named ? setName ?? fileName : counts
        let subtitle = named ? "\(counts) · \(format.style.name)" : format.style.name
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                FormatChip(format: format)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.title2.weight(.semibold))
                        .lineLimit(2)
                        .help(title)
                    Text(subtitle)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
            .padding([.top, .horizontal], 20)
            .padding(.bottom, 16)
            Divider()
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 160, maximum: 240), spacing: 16, alignment: .top)], spacing: 16) {
                    ForEach(cells.indices, id: \.self) { index in
                        cells[index]
                    }
                }
                .padding(20)
            }
        }
    }

    private func single(_ cell: BrushPreviewCell) -> some View {
        HStack(spacing: 28) {
            TipWell(cell: cell, cornerRadius: 12, tipPadding: 28)
                .frame(width: 380, height: 380)
            VStack(alignment: .leading, spacing: 4) {
                FormatChip(format: format)
                Text(cell.name)
                    .font(.title2.weight(.semibold))
                    .padding(.top, 12)
                Group {
                    Text(cell.dimensionsText)
                    Text(format.style.name)
                    if let setName, setName != cell.name {
                        Text("Set: \(setName)")
                    }
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(28)
        .frame(maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }
}

private struct FormatChip: View {
    let format: BrushFormat

    var body: some View {
        Text(format.style.badge)
            .font(.system(size: 10, weight: .bold))
            .foregroundStyle(.white)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(Color(cgColor: format.style.color), in: RoundedRectangle(cornerRadius: 5))
    }
}

struct BrushPreviewCell: View {
    let name: String
    let sourceDimensions: BrushSourceDimensions?
    let unavailableReason: String
    let image: CGImage?

    init(entry: BrushEntry) {
        name = entry.name
        sourceDimensions = entry.sourceDimensions
        if case let .unavailable(reason) = entry.tip {
            unavailableReason = reason
        } else {
            unavailableReason = "This tip could not be drawn."
        }
        image = BrushTipImage.make(from: entry.tip)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            TipWell(cell: self, cornerRadius: 8, tipPadding: 14)
                .frame(height: 150)
                .accessibilityHidden(true)
            Text(name)
                .font(.callout.weight(.medium))
                .lineLimit(2)
                .padding(.top, 10)
                .help(name)
            Text(dimensionsText)
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.top, 2)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(name), \(dimensionsText)\(image == nil ? ", No preview, \(unavailableReason)" : "")")
    }

    var dimensionsText: String {
        if let dimensions = sourceDimensions {
            "\(dimensions.width) × \(dimensions.height) px"
        } else {
            "Size unknown"
        }
    }
}

private struct TipWell: View {
    let cell: BrushPreviewCell
    let cornerRadius: CGFloat
    let tipPadding: CGFloat

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius)
        if let image = cell.image {
            // Small source tips stay crisp: never more than 2 pt per source pixel.
            let cap = cell.sourceDimensions.map { CGSize(width: CGFloat($0.width) * 2, height: CGFloat($0.height) * 2) }
            Image(decorative: image, scale: 1)
                .renderingMode(.template)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(maxWidth: cap?.width, maxHeight: cap?.height)
                .padding(tipPadding)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.primary.opacity(0.06), in: shape)
        } else {
            VStack(spacing: 4) {
                Image(systemName: "paintbrush.pointed")
                    .font(.title3)
                    .foregroundStyle(.secondary)
                    .opacity(0.6)
                Text("No preview")
                    .font(.callout.weight(.medium))
                Text(cell.unavailableReason)
                    .font(.caption)
                    .multilineTextAlignment(.center)
                    .lineLimit(3)
                    .help(cell.unavailableReason)
            }
            .foregroundStyle(.secondary)
            .padding(tipPadding)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .overlay(shape.strokeBorder(Color(nsColor: .separatorColor), style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
        }
    }
}
