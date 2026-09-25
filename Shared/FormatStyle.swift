import CoreGraphics

struct FormatStyle {
    let badge: String
    let name: String
    let color: CGColor
}

extension BrushFormat {
    var style: FormatStyle {
        let photoshop = CGColor(srgbRed: 0.184, green: 0.435, blue: 0.929, alpha: 1)
        let procreate = CGColor(srgbRed: 0.914, green: 0.412, blue: 0.173, alpha: 1)
        return switch self {
        case .abr: FormatStyle(badge: "ABR", name: "Photoshop brushes", color: photoshop)
        case .brush: FormatStyle(badge: "BRUSH", name: "Procreate brush", color: procreate)
        case .brushset: FormatStyle(badge: "BRUSHSET", name: "Procreate brush set", color: procreate)
        }
    }
}
