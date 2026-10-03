#!/bin/sh
set -eu

build=yes
if [ "${1-}" = --no-build ]; then
    build=no
    shift
fi
if [ "$#" -gt 1 ]; then
    printf 'Usage: %s [--no-build] [destination, default /Applications/BrushesQuickLook.app]\n' "$0" >&2
    exit 1
fi

fail() {
    printf 'FAIL %s %s\n' "$1" "$(printf '%s' "$2" | tr '\n\r' '  ')" >&2
    exit 1
}

destination=${1:-/Applications/BrushesQuickLook.app}
destination=${destination%/}
case "$destination" in
    /*/BrushesQuickLook.app) ;;
    *) fail destination "$destination must be an absolute path ending in BrushesQuickLook.app" ;;
esac
# app_pids compares this path with the one ps reports, so resolve symlinks and dots.
if [ -d "${destination%/*}" ]; then
    destination=$(cd -- "${destination%/*}" && pwd -P)/BrushesQuickLook.app
fi

cd -- "$(dirname "$0")/.."
app=$PWD/build.noindex/Build/Products/Release/BrushesQuickLook.app
lsregister=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
extensions='Preview Thumbnail'

if [ "$build" = yes ]; then
    observed=$(scripts/build.sh 2>&1) || fail build "$observed"
    printf 'ok build\n'
elif [ ! -d "$app" ]; then
    fail build "--no-build needs a Release build at $app"
fi

observed=$(scripts/check-build.sh "$app" 2>&1) || fail check-build "$observed"
printf 'ok check-build\n'

registered() {
    "$lsregister" -dump 2>/dev/null \
        | sed -n 's/^[[:space:]]*path:[[:space:]]*\(.*BrushesQuickLook\.app\).*$/\1/p' \
        | sort -u
}

stale=$(registered | grep -v -x -F -- "$destination" || :)
printf '%s\n' "$stale" | grep . | while IFS= read -r path; do
    "$lsregister" -u "$path" >/dev/null 2>&1 || :
done
printf 'ok unregister %s stale paths\n' "$(printf '%s\n' "$stale" | grep -c .)"

app_pids() {
    for pid in $(pgrep -x BrushesQuickLook || :); do
        case $(ps -o comm= -p "$pid" || :) in
            "$destination/Contents/MacOS/BrushesQuickLook") printf '%s\n' "$pid" ;;
        esac
    done
}

# The quit reply arrives before the process exits. `open` during the exit goes to the dying process.
deadline=$(($(date +%s) + 10))
quit=$(osascript -e 'with timeout of 10 seconds' -e 'tell application id "pl.esdesign.brushesquicklook" to quit' \
    -e 'end timeout' 2>&1) || :
running=$(app_pids)
while [ -n "$running" ]; do
    [ "$(date +%s)" -lt "$deadline" ] \
        || fail quit "pid $(printf '%s' "$running" | tr '\n' ' ') still runs $destination 10 s after the quit request.${quit:+ $quit}"
    sleep 0.2
    running=$(app_pids)
done
printf 'ok quit\n'

rm -rf -- "$destination"
observed=$(ditto "$app" "$destination" 2>&1) || fail replace "$observed"
printf 'ok replace\n'

"$lsregister" -f -R "$destination"
for name in $extensions; do
    pluginkit -a "$destination/Contents/PlugIns/Brushes$name.appex"
done
observed=$(open "$destination" 2>&1) || fail open "$observed"
for name in $extensions; do
    pluginkit -e use -i "pl.esdesign.brushesquicklook.$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"
done
printf 'ok register\n'

observed=$(registered)
[ "$observed" = "$destination" ] || fail verify "LaunchServices paths: $observed"
for name in $extensions; do
    id=pl.esdesign.brushesquicklook.$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')
    observed=$(pluginkit -m -v -A -i "$id" 2>&1 | grep -F "$id" || :)
    [ "$(printf '%s\n' "$observed" | grep -c .)" -eq 1 ] || fail verify "$id: $observed"
    case "$observed" in
        *"$destination/Contents/PlugIns/Brushes$name.appex") ;;
        *) fail verify "$id: $observed" ;;
    esac
    printf '%s\n' "$observed"
    executable=Contents/PlugIns/Brushes$name.appex/Contents/MacOS/Brushes$name
    for pid in $(pgrep -U "$(id -u)" -x "Brushes$name" || :); do
        path=$(ps -o comm= -p "$pid" || :)
        case "$path" in
            *"BrushesQuickLook.app/$executable") ;;
            *) continue ;;
        esac
        [ "$path" = "$destination/$executable" ] || fail verify "$id: pid $pid runs $path"
        observed=$(codesign -v "$pid" 2>&1) || { kill -0 "$pid" 2>/dev/null && fail verify "$id: pid $observed"; }
    done
done
printf 'ok verify\n'
