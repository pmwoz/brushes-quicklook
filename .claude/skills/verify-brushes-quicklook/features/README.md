# Brushes Quick Look verification map

This directory is the maintained source for verifying what a user sees from
Brushes Quick Look. Read this index before you drive the app. Then use the
matching feature file as the recipe.

## Baseline preconditions

- `bql doctor` exits 0, and its CDHashes match the Release build of the code under test.
- `bql fixtures` has run and `F=build.noindex/verify/fixtures/corpus` is set
  in the shell. `$F/<name>` in the recipes is one of its files.
- Real-world files, when needed, come from the folder in `BQL_REAL_FILES`.
  Never write their names into this map or into a commit.

## Driving conventions

- `bql` means `.claude/skills/verify-brushes-quicklook/bql`, run from the repo root.
- Drive the installed app only. Quick Look never loads the build folder's copy.
- Use `bql thumb` for thumbnails, `bql preview` for the space-bar preview, and
  `bql finder` when the Finder path itself is under test.
- Open every PNG the run lists and compare it with the expected state. The JSON
  says a drive ran, not that it drew the right thing.

## Proof and skip reporting

- Report the fixture, the command, the evidence folder and the doctor CDHashes.
- A preview proof names `extension.binary` from the JSON.
- `new_crash_reports` is empty in every run you report.
- If an entry point was not driven (for example `bql finder` without
  Accessibility), say so and give the error JSON. Do not count a `bql preview`
  run as a Finder proof.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the
behavior a user sees. It then has these four H2 sections, in order.

1. `Sub-features` gives each behavior a short ID and one line.
2. `How to get to it (user POV)` lists the user entry points.
3. `Driving it with bql` starts with `Preconditions:`, then pairs each action
   with an exact command and the observable result.
4. `Gotchas` lists traps that waste or invalidate a run.

## Features

- [Finder thumbnail](./thumbnail.md): the tip grid, the single tip, the badge and the strip, and the glyph states.
- [Space-bar preview](./preview.md): the grid, the single-brush layout, counts, names and sizes.
- [Error states](./error-states.md): the "No preview" cells, the damaged-file view, the size limit and crash safety.
- [Host app](./host-app.md): the install window and extension registration.
