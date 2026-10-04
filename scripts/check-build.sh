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

# Apple's required reason APIs as imported symbols and Objective-C selector names.
required_reason_apis="_NSFileCreationDate FileTimestamp
_NSFileModificationDate FileTimestamp
fileModificationDate FileTimestamp
_NSURLContentModificationDateKey FileTimestamp
_NSURLCreationDateKey FileTimestamp
_stat FileTimestamp
_fstat FileTimestamp
_fstatat FileTimestamp
_lstat FileTimestamp
_stat64 FileTimestamp
_fstat64 FileTimestamp
_lstat64 FileTimestamp
_getattrlistbulk FileTimestamp
_getattrlist FileTimestamp DiskSpace
_fgetattrlist FileTimestamp DiskSpace
_getattrlistat FileTimestamp DiskSpace
_mach_absolute_time SystemBootTime
systemUptime SystemBootTime
_NSURLVolumeAvailableCapacityKey DiskSpace
_NSURLVolumeAvailableCapacityForImportantUsageKey DiskSpace
_NSURLVolumeAvailableCapacityForOpportunisticUsageKey DiskSpace
_NSURLVolumeTotalCapacityKey DiskSpace
_NSFileSystemFreeSize DiskSpace
_NSFileSystemSize DiskSpace
_statfs DiskSpace
_statvfs DiskSpace
_fstatfs DiskSpace
_fstatvfs DiskSpace
_statfs64 DiskSpace
_fstatfs64 DiskSpace
_OBJC_CLASS_\$_NSUserDefaults UserDefaults"

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
    observed=$(plutil -lint "$manifest" 2>&1) || fail privacy "$observed"
    count=$(plutil -extract NSPrivacyAccessedAPITypes raw -expect array -o - "$manifest" 2>&1) || fail privacy "$count"
    declared=
    i=0
    while [ "$i" -lt "$count" ]; do
        category=$(plutil -extract "NSPrivacyAccessedAPITypes.$i.NSPrivacyAccessedAPIType" raw -expect string -o - "$manifest" 2>&1) \
            || fail privacy "$category"
        observed=$(plutil -extract "NSPrivacyAccessedAPITypes.$i.NSPrivacyAccessedAPITypeReasons.0" raw -o - "$manifest" 2>&1) \
            || fail privacy "$category has no reason: $observed"
        declared="$declared ${category#NSPrivacyAccessedAPICategory}"
        i=$((i + 1))
    done
    symbols=$(nm -u -j -arch all "$binary" 2>&1) || fail privacy "$symbols"
    selectors=$(otool -arch all -v -s __TEXT __objc_methname "$binary" 2>&1) || fail privacy "$selectors"
    observed=$(printf '%s\n%s\n' "$symbols" "$selectors" \
        | required_reason_apis="$required_reason_apis" declared="$declared" awk '
            BEGIN {
                if (!split(ENVIRON["required_reason_apis"], rows, "\n")) {
                    print "no required reason APIs"
                    exit 1
                }
                for (r in rows) {
                    n = split(rows[r], fields, " ")
                    for (c = 2; c <= n; c++) categories[fields[1]] = categories[fields[1]] " " fields[c]
                }
                declared = ENVIRON["declared"] " "
            }
            {
                name = $0
                if ($0 ~ /^[0-9a-f]+[ \t]/) name = $2
                sub(/[$]INODE64$/, "", name)
                if (!(name in categories)) next
                n = split(categories[name], needed, " ")
                for (c = 1; c <= n; c++) if (index(declared, " " needed[c] " ")) next
                message = name " needs NSPrivacyAccessedAPICategory" needed[1]
                for (c = 2; c <= n; c++) message = message " or NSPrivacyAccessedAPICategory" needed[c]
                print message
                exit 1
            }' 2>&1) || fail privacy "$observed"
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
