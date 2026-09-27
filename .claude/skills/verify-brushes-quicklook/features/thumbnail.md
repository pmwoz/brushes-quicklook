# Finder thumbnail

Finder icon view and column view show a brush file as a white card. The card holds its
first brush tips and a format badge: blue `ABR` for Photoshop and orange
`BRUSH` or `BRUSHSET` for Procreate. Small icons swap the badge for a coloured
strip. Files with no drawable tip show a brush glyph. Unreadable files show a
warning glyph.

## Sub-features

- `thumb-grid` shows a 2×2 grid of the first four drawable tips at 64 pt and up.
- `thumb-single` shows one tip when the file has one to three drawable tips, or at any size below 64 pt.
- `thumb-badge` shows the format pill at 64 pt and up.
- `thumb-strip` replaces the pill with a coloured strip along the bottom edge below 64 pt.
- `thumb-no-tips` shows a brush glyph for a file that parses but has no drawable tip.
- `thumb-unreadable` shows a warning glyph for a damaged file.

## How to get to it (user POV)

- Open a folder of brush files in Finder, icon view, and change the icon size.
- Column view and the Get Info window show the same thumbnail.

## Driving it with bql

Preconditions:

- Baseline preconditions from the index.

- **Single tip, badge.** Run `bql thumb $F/root_brush.brush $F/ordered_set.brushset $F/sampled_tip.abr --size 256`.
  Each PNG shows one grey tip and the matching badge. `ordered_set` has two
  tips, so it still shows one.
- **Strip.** Run `bql thumb $F/ordered_set.brushset --size 48`. The 48×48 PNG shows
  the tip with an orange strip along the bottom and no text.
- **No tips.** Run `bql thumb $F/missing_shape.brush $F/wellformed_v6_min.abr $F/bad_shapes.brushset --size 256`.
  Each PNG shows a grey brush glyph over the badge.
- **Unreadable.** Run `bql thumb $F/v2_rle_overflow.abr $F/deep_metadata.brushset --size 256`.
  Each PNG shows a grey warning triangle over the badge.
- **Zero-area tip skipped.** Run `bql thumb $F/zero_area_tip.abr --size 256`. The PNG
  shows the drawable tip, not an empty card.
- **Grid.** No corpus file has four drawable tips. Run
  `bql thumb "$BQL_REAL_FILES" --size 256` and pick a file with four or more
  brushes. The PNG shows a 2×2 grid in file order.
- **Proof.** The PNGs under `thumb/<size>pt@1x/` in the evidence folder, opened and compared with the states above.

## Gotchas

- `--size` is in points. `--scale 2` doubles the pixels but keeps the layout.
  The 64 pt threshold is in points, so `--size 48 --scale 2` still gets a strip.
- Plain `qlmanage -t` without `-x` hangs. `bql thumb` always passes `-x`.
- Finder keeps its own thumbnail cache. A Finder window can show an old
  thumbnail after an install even when `bql thumb` shows the new one. Trust
  `bql thumb` for the extension's output.
- A generic document icon in the PNG means the extension was not used. Run `bql doctor`.
