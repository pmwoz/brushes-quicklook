import AppKit

struct BrushThumbnail {
    enum Layout {
        case badgeOnly
        case single(CGImage)
        case grid([CGImage])
    }

    static let maxTips = 4

    static func tipCount(for size: CGSize) -> Int {
        min(size.width, size.height) >= 64 ? maxTips : 1
    }

    let badge: String
    let layout: Layout

    init(badge: String, tips: [BrushTip], size: CGSize) {
        self.badge = badge
        let images = Array(tips.lazy.compactMap { BrushTipImage.make(from: $0) }.prefix(Self.tipCount(for: size)))
        if images.count == Self.maxTips {
            layout = .grid(images)
        } else if let first = images.first {
            layout = .single(first)
        } else {
            layout = .badgeOnly
        }
    }

    static func load(_ url: URL, maximumSize: CGSize, scale: CGFloat) -> BrushThumbnail {
        let pixels = (max(maximumSize.width, maximumSize.height) * scale).rounded(.up)
        let maxCell = Int(min(max(pixels, 1), 256))
        let set = try? BrushPreviewSet.load(url, maxCell: maxCell, firstAvailable: tipCount(for: maximumSize), timeout: 5)
        return BrushThumbnail(
            badge: url.pathExtension.uppercased(),
            tips: set?.entries.map(\.tip) ?? [],
            size: maximumSize
        )
    }

    func draw(in context: CGContext, size: CGSize) {
        context.saveGState()
        defer { context.restoreGState() }
        let side = min(size.width, size.height)
        let card = CGRect(origin: .zero, size: size).insetBy(dx: side * 0.06, dy: side * 0.06)
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.setShadow(offset: CGSize(width: 0, height: -side * 0.01), blur: side * 0.02,
                          color: CGColor(gray: 0, alpha: 0.35))
        context.addPath(CGPath(roundedRect: card, cornerWidth: side * 0.06, cornerHeight: side * 0.06, transform: nil))
        context.fillPath()
        context.setShadow(offset: .zero, blur: 0, color: nil)

        let badgeHeight = side * 0.14
        let content = CGRect(
            x: card.minX, y: card.minY + badgeHeight + side * 0.04,
            width: card.width, height: card.height - badgeHeight - side * 0.04
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
        case .badgeOnly:
            break
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

        let font = NSFont.systemFont(ofSize: badgeHeight * 0.55, weight: .bold)
        let text = NSAttributedString(string: badge, attributes: [.font: font, .foregroundColor: NSColor.white])
        let line = CTLineCreateWithAttributedString(text)
        let bounds = CTLineGetImageBounds(line, context)
        let pill = CGRect(
            x: card.midX - (bounds.width + badgeHeight) / 2, y: card.minY + side * 0.04,
            width: bounds.width + badgeHeight, height: badgeHeight
        )
        context.setFillColor(CGColor(srgbRed: 0.2, green: 0.35, blue: 0.9, alpha: 1))
        context.addPath(CGPath(roundedRect: pill, cornerWidth: badgeHeight / 2, cornerHeight: badgeHeight / 2, transform: nil))
        context.fillPath()
        context.textMatrix = .identity
        context.textPosition = CGPoint(
            x: pill.midX - bounds.width / 2 - bounds.minX,
            y: pill.midY - bounds.height / 2 - bounds.minY
        )
        CTLineDraw(line, context)
    }
}
