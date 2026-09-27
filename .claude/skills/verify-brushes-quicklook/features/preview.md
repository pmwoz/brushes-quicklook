# Space-bar preview

Pressing space on a brush file in Finder opens a panel that lists every brush
in the file in file order. A multi-brush file shows a header with the format
chip, a title and a count line, then a grid of tip cells with the brush name
and source size. A file with one brush shows one large tip beside its name,
size and format.

## Sub-features

- `preview-grid` shows an adaptive grid of cells that gains columns as the panel widens.
- `preview-header-named` uses the set name as the title when it differs from the file name, with the count and format below.
- `preview-header-count` uses the count as the title when the set has no name of its own.
- `preview-single` shows one large tip with name, size and format for a one-brush file.
- `preview-size` shows `W × H px` when the source size is known and `Size unknown` otherwise.
- `preview-small-tip` keeps small tips crisp by never scaling past 2 pt per source pixel.
- `preview-order` keeps brushes in file order, not sorted by name.

## How to get to it (user POV)

- Select a brush file in Finder and press space.
- Right-click a brush file in Finder and choose Quick Look.

## Driving it with bql

Preconditions:

- Baseline preconditions from the index.
- For `bql finder`: Accessibility and Automation for Finder are granted, no Quick Look panel is open, and the user is not typing.

- **Named set, order.** Run `bql preview $F/ordered_set.brushset`. The PNG shows
  the title `Ordered`, the line `2 brushes · Procreate brush set`, and the
  cells `B` then `A`, each `16 × 8 px`.
- **Count title.** Run `bql preview $F/no_metadata.brushset`. The title is
  `2 brushes` and the subtitle is `Procreate brush set`.
- **Single brush.** Run `bql preview $F/root_brush.brush $F/sampled_tip.abr`. Each PNG
  shows one large tip well with the name, `16 × 8 px` and the format name beside it.
- **Small tip.** Run `bql preview $F/small_tip.abr`. The `4 × 4 px` tip stays a
  small square in the large well. It is not stretched to fill it.
- **Finder path.** Run `bql finder $F/ordered_set.brushset`. The PNG is Finder's
  panel, with no `[DEBUG]` title, and has the same content as the qlmanage run.
- **Large sets.** Run `bql preview "$BQL_REAL_FILES" --settle 5` for real multi-brush files.
  The grid fills several columns and the count matches the file.
- **Proof.** The PNGs under `preview/` in the evidence folder, and
  `extension.binary` under `/Applications/BrushesQuickLook.app` for each result.

## Gotchas

- The qlmanage window title carries `[DEBUG]`. That comes from qlmanage, not the extension.
- The qlmanage window may open on a second display. Capture by window id still works.
- The capture is taken `--settle` seconds after the window appears. A PNG that
  reads "Loading brushes…" means the settle time was too short, not that the preview failed.
- Finder's panel shows an "Open with" button for whichever app owns the
  extension on that Mac. It is not part of the extension.
- The ABR fixtures `wellformed_v6_min`, `wellformed_v6_patt` and `patt_*` parse
  to `0 brushes`. They check that nothing breaks, not the grid.
