// Generates App/Assets.xcassets/AppIcon.appiconset. Run: swift scripts/make-app-icon.swift
import CoreGraphics
import Foundation
import ImageIO

struct Slot {
    let points: Int
    let scale: Int

    var pixels: Int { points * scale }
    var filename: String { "icon_\(points)x\(points)\(scale == 2 ? "@2x" : "").png" }
}

let slots = [16, 32, 128, 256, 512].flatMap { points in [1, 2].map { Slot(points: points, scale: $0) } }

let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
let photoshop = CGColor(srgbRed: 0.184, green: 0.435, blue: 0.929, alpha: 1)
let procreate = CGColor(srgbRed: 0.914, green: 0.412, blue: 0.173, alpha: 1)

func color(_ base: CGColor, alpha: CGFloat) -> CGColor { base.copy(alpha: alpha)! }

func mix(_ from: CGFloat, _ to: CGFloat, _ t: CGFloat) -> CGFloat { from + (to - from) * t }

/// SplitMix64, so the splatter is identical on every run.
struct SeededGenerator: RandomNumberGenerator {
    var state: UInt64
    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }
}

struct Dot {
    let center: CGPoint
    let radius: CGFloat
    /// Length over width along the line from the origin, so far droplets look thrown outward.
    let stretch: CGFloat
}

/// Unit-space splatter around the origin within radius 1, largest dots first.
let splatter: [Dot] = {
    var generator = SeededGenerator(state: 98)
    var dots = [Dot(center: .zero, radius: 0.32, stretch: 1)]
    func random(_ range: ClosedRange<CGFloat>) -> CGFloat { CGFloat.random(in: range, using: &generator) }
    // Lobes just inside the main dab's edge make its outline irregular like wet paint.
    for index in 0..<5 {
        let angle = CGFloat(index) * 1.26 + random(0...0.6)
        let d = random(0.2...0.24)
        dots.append(Dot(center: CGPoint(x: cos(angle) * d, y: sin(angle) * d), radius: random(0.12...0.15), stretch: 1))
    }
    while dots.count < 26 {
        let angle = random(0...(2 * .pi))
        let far = pow(random(0...1), 0.8)
        let d = mix(0.44, 0.93, far)
        let dot = Dot(center: CGPoint(x: cos(angle) * d, y: sin(angle) * d),
                      radius: mix(0.1, 0.03, far) * random(0.6...1.3), stretch: mix(1, 1.9, far))
        let reach = dot.radius * dot.stretch
        let clear = dots.dropFirst().allSatisfy { other in
            hypot(other.center.x - dot.center.x, other.center.y - dot.center.y) > other.radius * other.stretch + reach + 0.02
        }
        if clear && d + reach <= 1 {
            dots.append(dot)
        }
    }
    return dots.sorted { $0.radius > $1.radius }
}()

func drawIcon(in context: CGContext, pixels: Int) {
    let side = CGFloat(pixels)
    // 0 at 16 px, 1 from 128 px up. Small sizes get bolder, simpler tips so the motif still reads.
    let detail = min(max((side - 16) / 112, 0), 1)
    let unit = side / 1024
    context.scaleBy(x: unit, y: unit)

    let body = CGRect(x: 100, y: 100, width: 824, height: 824)
    let bodyShape = CGPath(roundedRect: body, cornerWidth: 185, cornerHeight: 185, transform: nil)

    context.saveGState()
    // Shadows ignore the CTM, so they are scaled by hand.
    context.setShadow(offset: CGSize(width: 0, height: -10 * unit), blur: 24 * unit, color: CGColor(gray: 0, alpha: 0.35))
    context.addPath(bodyShape)
    context.setFillColor(CGColor(gray: 0, alpha: 1))
    context.fillPath()
    context.restoreGState()

    context.saveGState()
    context.addPath(bodyShape)
    context.clip()
    let background = CGGradient(colorsSpace: srgb, colors: [
        CGColor(srgbRed: 0.29, green: 0.33, blue: 0.56, alpha: 1),
        CGColor(srgbRed: 0.11, green: 0.12, blue: 0.25, alpha: 1),
    ] as CFArray, locations: [0, 1])!
    context.drawLinearGradient(background, start: CGPoint(x: 512, y: 924), end: CGPoint(x: 512, y: 100), options: [])
    context.restoreGState()

    // 640 keeps the card edges on whole pixels at 16 and 32 px.
    let card = CGRect(x: 192, y: 192, width: 640, height: 640)
    let cardRadius = mix(96, 60, detail)
    context.saveGState()
    context.setShadow(offset: CGSize(width: 0, height: -8 * unit), blur: 20 * unit, color: CGColor(gray: 0, alpha: 0.3))
    context.addPath(CGPath(roundedRect: card, cornerWidth: cardRadius, cornerHeight: cardRadius, transform: nil))
    context.setFillColor(CGColor(gray: 1, alpha: 1))
    context.fillPath()
    context.restoreGState()

    let padding = mix(64, 56, detail)
    let gap = mix(0, 36, detail)
    let cell = (card.width - 2 * padding - gap) / 2
    func cellRect(column: Int, row: Int) -> CGRect {
        CGRect(
            x: card.minX + padding + CGFloat(column) * (cell + gap),
            y: card.maxY - padding - CGFloat(row + 1) * cell - CGFloat(row) * gap,
            width: cell, height: cell
        )
    }

    drawSoftRound(in: context, rect: cellRect(column: 0, row: 0), detail: detail)
    drawHardRound(in: context, rect: cellRect(column: 1, row: 0), detail: detail)
    drawSplatter(in: context, rect: cellRect(column: 0, row: 1), detail: detail)
    drawTaperedStroke(in: context, rect: cellRect(column: 1, row: 1), detail: detail)
}

func drawSoftRound(in context: CGContext, rect: CGRect, detail: CGFloat) {
    // A gaussian-like falloff. Small sizes keep a solid core, or the dab turns into a faint smudge.
    let core = mix(0.45, 0.1, detail)
    let stops: [CGFloat] = [0, core, core + (1 - core) * 0.35, core + (1 - core) * 0.65, 1]
    let alphas: [CGFloat] = [1, 1, 0.72, 0.28, 0]
    let gradient = CGGradient(
        colorsSpace: srgb,
        colors: alphas.map { color(photoshop, alpha: $0) } as CFArray,
        locations: stops
    )!
    let center = CGPoint(x: rect.midX, y: rect.midY)
    context.drawRadialGradient(gradient, startCenter: center, startRadius: 0, endCenter: center, endRadius: rect.width / 2, options: [])
}

func drawHardRound(in context: CGContext, rect: CGRect, detail: CGFloat) {
    let inset = rect.width * mix(0.1, 0.13, detail)
    context.setFillColor(procreate)
    context.fillEllipse(in: rect.insetBy(dx: inset, dy: inset))
}

func drawSplatter(in context: CGContext, rect: CGRect, detail: CGFloat) {
    let unit = rect.width / 2
    let count = Int(mix(1, CGFloat(splatter.count), detail))
    context.setFillColor(procreate)
    for (index, dot) in splatter.prefix(count).enumerated() {
        let grow = index == 0 ? mix(1.9, 1, detail) : mix(1.4, 1, detail)
        let radius = dot.radius * unit * grow
        context.saveGState()
        context.translateBy(x: rect.midX + dot.center.x * unit, y: rect.midY + dot.center.y * unit)
        context.rotate(by: atan2(dot.center.y, dot.center.x))
        context.fillEllipse(in: CGRect(x: -radius * dot.stretch, y: -radius, width: radius * dot.stretch * 2, height: radius * 2))
        context.restoreGState()
    }
}

func drawTaperedStroke(in context: CGContext, rect: CGRect, detail: CGFloat) {
    let amplitude = mix(0.35, 0.8, detail)
    let p0 = CGPoint(x: -1, y: -0.4 * amplitude)
    let p1 = CGPoint(x: -0.3, y: amplitude)
    let p2 = CGPoint(x: 0.3, y: -amplitude)
    let p3 = CGPoint(x: 1, y: 0.4 * amplitude)
    let maxWidth = mix(0.8, 0.4, detail)

    func point(_ t: CGFloat) -> CGPoint {
        let u = 1 - t
        let a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t
        return CGPoint(x: a * p0.x + b * p1.x + c * p2.x + d * p3.x, y: a * p0.y + b * p1.y + c * p2.y + d * p3.y)
    }

    let samples = 128
    var left: [CGPoint] = []
    var right: [CGPoint] = []
    for index in 0...samples {
        let t = CGFloat(index) / CGFloat(samples)
        let ahead = point(min(t + 0.005, 1)), behind = point(max(t - 0.005, 0))
        let dx = ahead.x - behind.x, dy = ahead.y - behind.y
        let length = hypot(dx, dy)
        // Peaks early and trails off, like a stroke that lands with pressure and lifts away.
        let half = maxWidth / 2 * pow(sin(.pi * pow(t, 0.75)), 0.8)
        let center = point(t)
        left.append(CGPoint(x: center.x - dy / length * half, y: center.y + dx / length * half))
        right.append(CGPoint(x: center.x + dy / length * half, y: center.y - dx / length * half))
    }
    let outline = CGMutablePath()
    outline.addLines(between: left + right.reversed())
    outline.closeSubpath()

    let bounds = outline.boundingBoxOfPath
    let target = rect.insetBy(dx: rect.width * 0.04, dy: rect.height * 0.04)
    let scale = min(target.width / bounds.width, target.height / bounds.height)
    var transform = CGAffineTransform(translationX: target.midX, y: target.midY)
        .scaledBy(x: scale, y: scale)
        .translatedBy(x: -bounds.midX, y: -bounds.midY)
    context.addPath(outline.copy(using: &transform)!)
    context.setFillColor(photoshop)
    context.fillPath()
}

func writePNG(pixels: Int, to url: URL) throws {
    guard let context = CGContext(
        data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: 0,
        space: srgb, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else { throw CocoaError(.fileWriteUnknown) }
    drawIcon(in: context, pixels: pixels)
    guard let image = context.makeImage(),
          let destination = CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil)
    else { throw CocoaError(.fileWriteUnknown) }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else { throw CocoaError(.fileWriteUnknown) }
}

struct AssetContents: Encodable {
    struct Image: Encodable {
        let filename: String
        let idiom = "mac"
        let scale: String
        let size: String
    }
    struct Info: Encodable {
        let author = "xcode"
        let version = 1
    }
    var images: [Image]? = nil
    let info = Info()
}

func writeJSON(_ contents: AssetContents, to url: URL) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    try (encoder.encode(contents) + Data("\n".utf8)).write(to: url)
}

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let catalog = root.appending(path: "App/Assets.xcassets")
let iconSet = catalog.appending(path: "AppIcon.appiconset")
try FileManager.default.createDirectory(at: iconSet, withIntermediateDirectories: true)

for slot in slots {
    try writePNG(pixels: slot.pixels, to: iconSet.appending(path: slot.filename))
}
try writeJSON(AssetContents(), to: catalog.appending(path: "Contents.json"))
try writeJSON(AssetContents(images: slots.map {
    .init(filename: $0.filename, scale: "\($0.scale)x", size: "\($0.points)x\($0.points)")
}), to: iconSet.appending(path: "Contents.json"))
print("Wrote \(slots.count) icons to \(iconSet.path(percentEncoded: false))")
