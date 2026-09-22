#!/bin/sh
# Previews every file in a folder through Finder's Quick Look and reports which ones the
# BrushesPreview extension handled, what it showed, and whether it crashed.
#
#   scripts/preview-hostile.sh <folder> [screenshot dir]
#
# Needs the app registered once (copy to /Applications and open it), Accessibility and
# Screen Recording granted to the terminal, and an idle Finder: the script drives the
# selection and the space bar. Build the folder from real files first, for example:
#   : > zero.abr; head -c 4096 real.abr > truncated.abr; head -c 50000000 real.brushset > cut.brushset
set -eu

folder=${1%/}
shots=${2:-/tmp/preview-hostile}
mkdir -p "$shots"
reports() { ls ~/Library/Logs/DiagnosticReports/ 2>/dev/null | grep -c -i '^Brushes' || true; }

# Finder's Quick Look panel is the Finder-owned window on layer 3.
panel_id() {
    osascript -l JavaScript -e '
        ObjC.import("CoreGraphics");
        const list = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(
            $.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements, $.kCGNullWindowID)));
        const w = list.find(w => w.kCGWindowOwnerName === "Finder" && w.kCGWindowLayer === 3);
        w ? String(w.kCGWindowNumber) : "";' 2>/dev/null
}

pkill -x BrushesPreview 2>/dev/null || true
before=$(reports)
started=$(date '+%Y-%m-%d %H:%M:%S')
osascript -e 'tell application "System Events" to key code 53' >/dev/null 2>&1

for file in "$folder"/*; do
    name=${file##*/}
    osascript >/dev/null 2>&1 <<APPLESCRIPT
        tell application "Finder"
            activate
            close every Finder window
            set w to make new Finder window to (POSIX file "$folder" as alias)
            select (POSIX file "$file" as alias)
        end tell
        delay 1
        tell application "System Events" to keystroke " "
        delay 5
APPLESCRIPT
    id=$(panel_id)
    if [ -z "$id" ]; then
        # The space bar toggles the panel, so a stray press closed it. Press once more.
        osascript -e 'tell application "System Events" to keystroke " "' >/dev/null 2>&1
        sleep 5
        id=$(panel_id)
    fi
    if [ -n "$id" ]; then
        screencapture -x -o -l "$id" "$shots/$name.png"
        printf 'shot  %s\n' "$name"
    else
        printf 'NOPANEL %s\n' "$name"
    fi
    osascript -e 'tell application "System Events" to key code 53' >/dev/null 2>&1
    sleep 1
done
osascript -e 'tell application "Finder" to close every Finder window' >/dev/null 2>&1

handled=$(/usr/bin/log show --start "$started" --info --debug --style compact \
    --predicate 'process == "Finder" AND eventMessage CONTAINS "pl.esdesign.brushesquicklook.preview"' 2>/dev/null \
    | grep -c 'tearing down extension request' || true)
printf 'handled by BrushesPreview: %s of %s\n' "$handled" "$(ls "$folder" | wc -l | tr -d ' ')"
printf 'extension process alive: %s\n' "$(pgrep -x BrushesPreview || echo no)"
printf 'crash reports before/after: %s/%s\n' "$before" "$(reports)"
printf 'screenshots: %s\n' "$shots"
