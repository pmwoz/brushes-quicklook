import AppKit
import SwiftUI

struct PreviewGrid: View {
    let fileName: String
    let format: BrushFormat
    let setName: String?
    let cells: [BrushPreviewCell]
    let notReached: Int

    init(fileName: String, format: BrushFormat, set: BrushPreviewSet) {
        self.fileName = fileName
        self.format = format
        setName = set.name
        cells = set.entries.map(BrushPreviewCell.init)
        notReached = set.notReached
    }

    nonisolated static func header(
        fileName: String, setName: String?, brushes: Int, unavailable: Int
    ) -> (title: String, subtitle: String?) {
        let count = "\(brushes) \(brushes == 1 ? "brush" : "brushes")"
        let withoutPreview: String? = switch unavailable {
        case 0: nil
        case brushes: "all without preview"
        default: "\(unavailable) without preview"
        }
        guard let setName, setName != (fileName as NSString).deletingPathExtension else {
            return (count, withoutPreview)
        }
        return (setName, [count, withoutPreview].compactMap { $0 }.joined(separator: " · "))
    }

    nonisolated static func notReachedText(_ count: Int) -> String {
        let seconds = (LoadBudget.previewTimeLimit / .seconds(1)).formatted()
        let brushes = count == 1 ? "brush was" : "brushes were"
        return "\(count) more \(brushes) not loaded. Previews stop loading after \(seconds) seconds."
    }

    var body: some View {
        Group {
            if cells.count == 1, notReached == 0, let cell = cells.first {
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
        let header = Self.header(
            fileName: fileName, setName: setName,
            brushes: cells.count + notReached,
            unavailable: cells.filter { $0.image == nil }.count + notReached
        )
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                FormatChip(format: format)
                VStack(alignment: .leading, spacing: 2) {
                    Text(header.title)
                        .font(.title2.weight(.semibold))
                        .lineLimit(2)
                        .help(header.title)
                    if let subtitle = header.subtitle {
                        Text(subtitle)
                            .font(.body)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
            Divider()
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 160, maximum: 240), spacing: 16, alignment: .top)], spacing: 16) {
                    ForEach(cells.indices, id: \.self) { index in
                        cells[index]
                    }
                }
                .padding(20)
                if notReached > 0 {
                    Text(Self.notReachedText(notReached))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding([.horizontal, .bottom], 20)
                }
            }
        }
    }

    private func single(_ cell: BrushPreviewCell) -> some View {
        // ViewThatFits measures each branch at its ideal size, so the well states the size it wants.
        let well = TipWell(cell: cell, cornerRadius: 12, tipPadding: 28)
            .aspectRatio(1, contentMode: .fit)
            .frame(idealWidth: 380, maxWidth: 380, idealHeight: 380, maxHeight: 380)
            .layoutPriority(1)
        let text = VStack(alignment: .leading, spacing: 4) {
            FormatChip(format: format)
            Text(cell.name)
                .font(.title2.weight(.semibold))
                .lineLimit(3)
                .padding(.top, 8)
                .help(cell.name)
            Group {
                Text(cell.dimensionsText)
                if let setName, setName != cell.name {
                    Text("Set: \(setName)")
                }
            }
            .font(.body)
            .foregroundStyle(.secondary)
        }
        let textOnFullLines = text.fixedSize(horizontal: true, vertical: false)
        let textWrappedBesideSmallerWell = text.frame(minWidth: 160, alignment: .leading)
        return ViewThatFits(in: .horizontal) {
            HStack(spacing: 24) {
                well
                textOnFullLines
            }
            HStack(spacing: 24) {
                well
                textWrappedBesideSmallerWell
            }
        }
        .frame(maxWidth: 720)
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }
}

private struct FormatChip: View {
    let format: BrushFormat

    var body: some View {
        Text(format.style.badge)
            .font(.caption2.weight(.bold))
            .foregroundStyle(.white)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Color(cgColor: format.style.color), in: Capsule())
            .help(format.style.name)
            .accessibilityLabel(format.style.name)
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
                .padding(.top, 8)
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
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        if let image = cell.image {
            // Small source tips stay crisp: never more than 2 pt per source pixel.
            let sourcePixels = cell.sourceDimensions.map { CGSize(width: CGFloat($0.width), height: CGFloat($0.height)) }
                ?? CGSize(width: image.width, height: image.height)
            Image(decorative: image, scale: 1)
                .renderingMode(.template)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(
                    maxWidth: sourcePixels.width * BrushTipImage.maxPointsPerSourcePixel,
                    maxHeight: sourcePixels.height * BrushTipImage.maxPointsPerSourcePixel
                )
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
                Text(cell.unavailableReason.keepingLastTwoWordsTogether)
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

extension String {
    var keepingLastTwoWordsTogether: String {
        guard let lastSpace = lastIndex(of: " ") else { return self }
        return replacingCharacters(in: lastSpace...lastSpace, with: "\u{00A0}")
    }
}
