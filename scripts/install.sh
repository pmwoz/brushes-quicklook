#!/bin/sh
set -eu

if [ "$#" -gt 1 ]; then
    printf 'Usage: %s [destination, default /Applications/BrushesQuickLook.app]\n' "$0" >&2
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

cd -- "$(dirname "$0")/.."
app=$PWD/build.noindex/Build/Products/Release/BrushesQuickLook.app
lsregister=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
extensions='Preview Thumbnail'

observed=$(xcodegen generate 2>&1) || fail build "$observed"
observed=$(xcodebuild -project BrushesQuickLook.xcodeproj -scheme BrushesQuickLook \
    -configuration Release ONLY_ACTIVE_ARCH=NO -derivedDataPath build.noindex -quiet build 2>&1) \
    || fail build "$observed"
printf 'ok build\n'

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

osascript -e 'tell application id "pl.esdesign.brushesquicklook" to quit' >/dev/null 2>&1 || :
rm -rf -- "$destination"
observed=$(ditto "$app" "$destination" 2>&1) || fail replace "$observed"
printf 'ok replace\n'

"$lsregister" -f -R "$destination"
for name in $extensions; do
    pluginkit -a "$destination/Contents/PlugIns/Brushes$name.appex"
done
open "$destination"
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
done
printf 'ok verify\n'
