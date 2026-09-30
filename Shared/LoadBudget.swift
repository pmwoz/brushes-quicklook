import Foundation

struct LoadBudget: Sendable {
    /// Files above this many bytes are refused before any byte reaches the parser.
    static let maxFileSize = 512 << 20
    /// A 512 pt thumbnail at 2x.
    static let maxCell = 1024
    /// How long a load waits past its time limit before it gives up on the parser. The parser checks
    /// the time only between brushes, so reading the file, parsing its index and the brush in progress
    /// can run over.
    static let grace: Duration = .seconds(1)

    enum Entries: Sendable {
        /// A file with one brush is decoded again at `singleBrushCell` from the same bytes, inside the same time limit.
        case all(singleBrushCell: Int?)
        case firstAvailable(Int)
    }

    /// The longest side, in pixels, a tip is decoded at.
    let cell: Int
    let entries: Entries
    let timeLimit: Duration

    init(cell: Int, entries: Entries, timeLimit: Duration) {
        self.cell = Self.clamped(cell)
        self.entries = switch entries {
        case .all(let singleBrushCell): .all(singleBrushCell: singleBrushCell.map(Self.clamped))
        case .firstAvailable: entries
        }
        self.timeLimit = timeLimit
    }

    static let previewTimeLimit: Duration = .seconds(10)

    /// A single brush fills a 380 pt well, so it is decoded at a size that stays sharp there. A `.brush`
    /// always holds one brush and is decoded at that size once. A set is decoded again only when it
    /// turns out to hold one brush.
    static func preview(_ format: BrushFormat) -> LoadBudget {
        let singleBrushCell = 768
        return switch format {
        case .brush: LoadBudget(cell: singleBrushCell, entries: .all(singleBrushCell: nil), timeLimit: previewTimeLimit)
        case .abr, .brushset: LoadBudget(cell: 256, entries: .all(singleBrushCell: singleBrushCell), timeLimit: previewTimeLimit)
        }
    }

    static func thumbnail(maximumSize: CGSize, scale: CGFloat, tips: Int) -> LoadBudget {
        let pixels = (max(maximumSize.width, maximumSize.height) * scale).rounded(.up)
        return LoadBudget(cell: Int(min(pixels, CGFloat(maxCell))), entries: .firstAvailable(tips), timeLimit: .seconds(5))
    }

    private static func clamped(_ cell: Int) -> Int {
        min(max(cell, 1), maxCell)
    }
}
