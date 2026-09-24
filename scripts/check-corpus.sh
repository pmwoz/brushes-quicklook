#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

metadata=$(cargo metadata --manifest-path ffi/Cargo.toml --format-version 1)
manifest=$(printf '%s\n' "$metadata" \
    | jq -r '.packages[] | select(.name == "brushkit-preview") | .manifest_path')
if [ -z "$manifest" ]; then
    printf 'FAIL brushkit-preview not found in cargo metadata\n'
    exit 1
fi
root=$(cargo locate-project --workspace --message-format plain --manifest-path "$manifest")
upstream=${root%/*}/fuzz/corpus

status=0
for dir in "$upstream"/preview_*; do
    if [ ! -d "$dir" ]; then
        printf 'FAIL no preview_* corpus in %s\n' "$upstream"
        exit 1
    fi
    name=${dir##*/}
    if diff -r -x .DS_Store "$dir" "ffi/tests/corpus/$name"; then
        printf 'ok %s\n' "$name"
    else
        printf 'FAIL %s\n' "$name"
        status=1
    fi
done
for dir in ffi/tests/corpus/*; do
    name=${dir##*/}
    case $name in
        preview_*) [ -d "$upstream/$name" ] && continue ;;
    esac
    printf 'FAIL %s is not a brushkit preview_* corpus\n' "$name"
    status=1
done
exit "$status"
