#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    printf 'Usage: %s <path to BrushesQuickLook.app>\n' "$0" >&2
    exit 1
fi

fail() {
    printf 'FAIL %s %s %s\n' "${bundle##*/}" "$1" "$(printf '%s' "$2" | tr '\n\r' '  ')"
    exit 1
}

app=${1%/}
for bundle in "$app" \
    "$app/Contents/PlugIns/BrushesPreview.appex" \
    "$app/Contents/PlugIns/BrushesThumbnail.appex"; do
    name=${bundle##*/}
    binary="$bundle/Contents/MacOS/${name%.*}"

    observed=$(lipo -archs "$binary" 2>&1) || fail lipo "$observed"
    case " $observed " in
        *" x86_64 "*) ;;
        *) fail lipo "$observed" ;;
    esac
    case " $observed " in
        *" arm64 "*) ;;
        *) fail lipo "$observed" ;;
    esac
    printf 'ok %s lipo\n' "$name"

    observed=$(codesign -dv "$bundle" 2>&1) || fail runtime "$observed"
    observed=$(printf '%s\n' "$observed" | sed -n 's/.*flags=\([^[:space:]]*\).*/\1/p')
    printf '%s\n' "$observed" | grep -Eq '[(,]runtime[),]' || fail runtime "$observed"
    printf 'ok %s runtime\n' "$name"

    observed=$(codesign -d --entitlements - "$bundle" 2>&1) || fail app-sandbox "$observed"
    printf '%s\n' "$observed" | grep -Fq 'com.apple.security.app-sandbox' || fail app-sandbox "$observed"
    printf 'ok %s app-sandbox\n' "$name"

    if [ "$bundle" = "$app" ]; then
        key=UTImportedTypeDeclarations
    else
        key=NSExtension.NSExtensionAttributes.QLSupportedContentTypes
    fi
    observed=$(plutil -extract "$key" json -o - "$bundle/Contents/Info.plist" 2>&1) || fail "${key##*.}" "$observed"
    for identifier in pl.esdesign.brushesquicklook.abr \
        pl.esdesign.brushesquicklook.brush \
        pl.esdesign.brushesquicklook.brushset; do
        printf '%s\n' "$observed" | grep -Fq "\"$identifier\"" || fail "${key##*.}" "$observed"
    done
    printf 'ok %s %s\n' "$name" "${key##*.}"
done
