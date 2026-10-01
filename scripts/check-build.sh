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

    observed=$(codesign -d --entitlements :- "$bundle" 2>/dev/null \
        | plutil -extract 'com\.apple\.security\.app-sandbox' raw -o - - 2>&1) || fail app-sandbox "$observed"
    [ "$observed" = true ] || fail app-sandbox "$observed"
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

    manifest="$bundle/Contents/Resources/PrivacyInfo.xcprivacy"
    observed=$(plutil -extract NSPrivacyAccessedAPITypes.0.NSPrivacyAccessedAPIType raw -o - "$manifest" 2>&1) || fail privacy "$observed"
    [ "$observed" = NSPrivacyAccessedAPICategoryFileTimestamp ] || fail privacy "$observed"
    observed=$(plutil -extract NSPrivacyAccessedAPITypes.0.NSPrivacyAccessedAPITypeReasons.0 raw -o - "$manifest" 2>&1) || fail privacy "$observed"
    [ "$observed" = C617.1 ] || fail privacy "$observed"
    printf 'ok %s privacy\n' "$name"
done

bundle=$app
observed=$(plutil -extract CFBundleIconName raw -o - "$app/Contents/Info.plist" 2>&1) || fail icon "$observed"
[ "$observed" = AppIcon ] || fail icon "$observed"
[ -f "$app/Contents/Resources/AppIcon.icns" ] || fail icon "no Contents/Resources/AppIcon.icns"
printf 'ok %s icon\n' "${app##*/}"

observed=$(plutil -extract LSApplicationCategoryType raw -o - "$app/Contents/Info.plist" 2>&1) || fail category "$observed"
[ "$observed" = public.app-category.graphics-design ] || fail category "$observed"
printf 'ok %s category\n' "${app##*/}"

observed=$(plutil -extract ITSAppUsesNonExemptEncryption raw -o - "$app/Contents/Info.plist" 2>&1) || fail encryption "$observed"
[ "$observed" = false ] || fail encryption "$observed"
printf 'ok %s encryption\n' "${app##*/}"
