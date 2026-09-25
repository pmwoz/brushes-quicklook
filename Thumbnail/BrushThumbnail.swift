import AppKit

struct BrushThumbnail {
    enum Layout {
        case empty(EmptyReason)
        case single(CGImage)
        case grid([CGImage])
    }

    enum EmptyReason {
        case noTips, unreadable
    }

    enum Badge {
        case pill, strip
    }

    static let maxTips = 4

    private static func isLarge(_ size: CGSize) -> Bool {
        min(size.width, size.height) >= 64
    }

    static func tipCount(for size: CGSize) -> Int {
        isLarge(size) ? maxTips : 1
    }

    let format: BrushFormat
    let badge: Badge
    let layout: Layout

    init(format: BrushFormat, tips: [BrushTip], size: CGSize) {
        let images = Array(tips.lazy.compactMap { BrushTipImage.make(from: $0) }.prefix(Self.tipCount(for: size)))
        let layout: Layout = if images.count == Self.maxTips {
            .grid(images)
        } else if let first = images.first {
            .single(first)
        } else {
            .empty(.noTips)
        }
        self.init(format: format, layout: layout, size: size)
    }

    private init(format: BrushFormat, layout: Layout, size: CGSize) {
        self.format = format
        badge = Self.isLarge(size) ? .pill : .strip
        self.layout = layout
    }

    /// Throws only for an extension that is not a brush format. Load errors become the unreadable state.
    static func load(_ url: URL, maximumSize: CGSize, scale: CGFloat) throws -> BrushThumbnail {
        let format = try BrushFormat(url: url)
        let pixels = (max(maximumSize.width, maximumSize.height) * scale).rounded(.up)
        let maxCell = Int(min(max(pixels, 1), 256))
        guard let set = try? BrushPreviewSet.load(url, maxCell: maxCell, firstAvailable: tipCount(for: maximumSize), timeout: 5) else {
            return BrushThumbnail(format: format, layout: .empty(.unreadable), size: maximumSize)
        }
        return BrushThumbnail(format: format, tips: set.entries.map(\.tip), size: maximumSize)
    }

    func draw(in context: CGContext, size: CGSize) {
        context.saveGState()
        defer { context.restoreGState() }
        let side = min(size.width, size.height)
        let card = CGRect(origin: .zero, size: size).insetBy(dx: side * 0.06, dy: side * 0.06)
        let cardShape = CGPath(roundedRect: card, cornerWidth: side * 0.06, cornerHeight: side * 0.06, transform: nil)
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.setShadow(offset: CGSize(width: 0, height: -side * 0.01), blur: side * 0.02,
                          color: CGColor(gray: 0, alpha: 0.35))
        context.addPath(cardShape)
        context.fillPath()
        context.setShadow(offset: .zero, blur: 0, color: nil)

        let pillHeight = side * 0.14
        let stripHeight = max(2, side * 0.09)
        let reserved = switch badge {
        case .pill: pillHeight + side * 0.04
        case .strip: stripHeight
        }
        let content = CGRect(
            x: card.minX, y: card.minY + reserved,
            width: card.width, height: card.height - reserved
        ).insetBy(dx: side * 0.06, dy: side * 0.04)
        context.setFillColor(CGColor(gray: 0.1, alpha: 1))
        context.interpolationQuality = .high

        func fit(_ image: CGImage, in rect: CGRect) {
            let scale = min(rect.width / CGFloat(image.width), rect.height / CGFloat(image.height))
            let width = CGFloat(image.width) * scale
            let height = CGFloat(image.height) * scale
            context.draw(image, in: CGRect(x: rect.midX - width / 2, y: rect.midY - height / 2, width: width, height: height))
        }

        switch layout {
        case let .empty(reason):
            let symbol = switch reason {
            case .noTips: "paintbrush.pointed"
            case .unreadable: "exclamationmark.triangle"
            }
            let glyph = side * 0.38
            drawSymbol(symbol, in: CGRect(
                x: card.midX - glyph / 2, y: card.maxY - card.height * 0.42 - glyph / 2,
                width: glyph, height: glyph
            ), context: context)
        case let .single(image):
            fit(image, in: content)
        case let .grid(images):
            let gap = side * 0.03
            let width = (content.width - gap) / 2
            let height = (content.height - gap) / 2
            for (index, image) in images.enumerated() {
                let column = CGFloat(index % 2)
                let row = CGFloat(index / 2)
                fit(image, in: CGRect(
                    x: content.minX + column * (width + gap),
                    y: content.maxY - (row + 1) * height - row * gap,
                    width: width, height: height
                ))
            }
        }

        let style = format.style
        context.setFillColor(style.color)
        switch badge {
        case .pill:
            let font = NSFont.systemFont(ofSize: pillHeight * 0.55, weight: .bold)
            let text = NSAttributedString(string: style.badge, attributes: [.font: font, .foregroundColor: NSColor.white])
            let line = CTLineCreateWithAttributedString(text)
            let bounds = CTLineGetImageBounds(line, context)
            let pill = CGRect(
                x: card.midX - (bounds.width + pillHeight) / 2, y: card.minY + side * 0.04,
                width: bounds.width + pillHeight, height: pillHeight
            )
            context.addPath(CGPath(roundedRect: pill, cornerWidth: pillHeight / 2, cornerHeight: pillHeight / 2, transform: nil))
            context.fillPath()
            context.textMatrix = .identity
            context.textPosition = CGPoint(
                x: pill.midX - bounds.width / 2 - bounds.minX,
                y: pill.midY - bounds.height / 2 - bounds.minY
            )
            CTLineDraw(line, context)
        case .strip:
            context.addPath(cardShape)
            context.clip()
            context.fill(CGRect(x: card.minX, y: card.minY, width: card.width, height: stripHeight))
        }
    }

    /// Draws through a context wrapped for this call only, because Quick Look calls the
    /// drawing block off the main thread with no current NSGraphicsContext.
    private func drawSymbol(_ name: String, in rect: CGRect, context: CGContext) {
        let configuration = NSImage.SymbolConfiguration(pointSize: rect.height, weight: .regular)
            .applying(NSImage.SymbolConfiguration(paletteColors: [.black]))
        guard let image = NSImage(systemSymbolName: name, accessibilityDescription: nil)?
            .withSymbolConfiguration(configuration) else { return }
        let scale = min(rect.width / image.size.width, rect.height / image.size.height)
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        image.draw(
            in: CGRect(x: rect.midX - size.width / 2, y: rect.midY - size.height / 2, width: size.width, height: size.height),
            from: .zero, operation: .sourceOver, fraction: 0.22
        )
    }
}
