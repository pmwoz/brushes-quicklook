# Error states

A brush that cannot be drawn gets a dashed "No preview" cell that says why.
It is never skipped silently. A file that cannot be read at all shows "This
file can’t be previewed" with a plain message, and damaged files add a Details
disclosure. Files above 512 MB are refused before parsing. A hostile file
never crashes either extension.

## Sub-features

- `error-cell` shows a dashed cell with a brush glyph, "No preview" and the reason, and the brush still counts.
- `error-counts` shows `N brushes · M without preview` in the multi-brush header, or `· none can be previewed yet` when no brush has a preview.
- `error-damaged` shows the warning view with "The file looks damaged or incomplete." and a Details disclosure holding the parser's message.
- `error-partial` shows the brushes loaded when the 10 s limit stops a load, plus `N more brushes were not loaded. Previews stop loading after 10 seconds.`
- `error-too-large` shows "This file is 600 MB. Files above 512 MB are not previewed." with no Details, and the thumbnail shows a brush glyph.
- `error-no-crash` means no hostile file produces a `BrushesPreview`, `BrushesThumbnail` or `BrushesQuickLook` crash report.

## How to get to it (user POV)

- Press space on a damaged, truncated or oversized brush file in Finder.
- Browse a folder of such files in Finder icon view.

## Driving it with bql

Preconditions:

- Baseline preconditions from the index.

- **Cells with reasons.** Run `bql preview $F/bad_shapes.brushset $F/zero_area_tip.abr`.
  `bad_shapes` reads `2 brushes · none can be previewed yet` and its cells say
  "This brush has no shape image." and "failed to decode Shape.png…".
  `zero_area_tip` reads `2 brushes · 1 without preview`, with one "tip has zero area" cell.
- **Single-brush cell.** Run `bql preview $F/missing_shape.brush $F/oversized_png.brush $F/deep_archive.brush $F/corrupt_shape.brush`.
  Each PNG shows the large dashed well with the reason, for example "The shape
  image is 60000 × 60000 px, too large to preview."
- **Damaged file.** Run `bql preview $F/v2_rle_overflow.abr $F/deep_metadata.brushset`.
  Each PNG shows the triangle, "This file can’t be previewed", "The file looks
  damaged or incomplete." and a collapsed "Details".
- **Too large.** Create a sparse file with `mkfile -n 600m build.noindex/verify/fixtures/too_large.abr`,
  which uses almost no disk. Run `bql thumb build.noindex/verify/fixtures/too_large.abr --size 256`
  and `bql preview build.noindex/verify/fixtures/too_large.abr`. The thumbnail
  shows the brush glyph and the preview shows the 600 MB message. `bql cleanup`
  deletes the file.
- **No crash.** Run `bql hostile`. It thumbnails and previews each file and
  opens it in a new `BrushesQuickLook` instance, which it captures once the
  load ends. Exit 0 with `crashed: 0`,
  `unexercised: []` and `retried` at most `retry_limit` across the whole corpus. With `BQL_REAL_FILES` set, the sweep includes those files too.
- **Proof.** The PNGs and the `result.json` of the `hostile` run. The run is
  proven to fail: a `SIGSEGV` sent to its own extension process gave exit 1
  and one report with `likely_file`. During `bql hostile small_tip.abr ordered_set.brushset`,
  a `SIGSEGV` sent to the second app instance gave exit 1, one
  `BrushesQuickLook` report with `likely_file` `ordered_set.brushset`, and the
  row problem "the app exited while it showed the file". The cap alone is proven to fail a run.
  During the crash wait of a `bql thumb` run, a new `Brushes*` report with a
  `captureTime` inside the run, written every 10 s for 100 s and deleted 5 s
  after each write, gave exit 1 with `crash_wait_capped: true` and an empty
  `new_crash_reports`.

## Gotchas

- `bql` cannot click, so Details stays collapsed. The parser text behind it is
  covered by `PreviewTests`, not here.
- The time-out state ("Previewing took longer than 10 seconds.") and
  `error-partial` have no fixture. They need a real file that parses for longer
  than 10 s.
- ReportCrash can write a report 25 s after the crash. `thumb`, `preview`, `finder`
  and `hostile` wait at the end until no new report from the run has arrived for
  30 s, at most 120 s, then collect every new report from the run. A wait that
  reaches 120 s without 30 quiet seconds sets `crash_wait_capped: true` and
  fails the run.
  `likely_file` is the last file that started before the `captureTime` in the
  report, so confirm it by rerunning `bql hostile <that file>`.
- A crash from before the run does not count, even when its report arrives
  during the run. Only a new `Brushes*` report from the run, or one that
  cannot be parsed yet, restarts the 30 s wait. A deletion does not. The cap
  still fails a run whose restarting reports were later deleted or turned out
  to predate the run.
