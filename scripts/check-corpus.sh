#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

manifest=$(cargo metadata --manifest-path ffi/Cargo.toml --format-version 1 \
    | jq -r '.packages[] | select(.name == "brushkit-preview") | .manifest_path')
if [ -z "$manifest" ]; then
    printf 'FAIL brushkit-preview not found in cargo metadata\n'
    exit 1
fi
root=$(cargo locate-project --workspace --message-format plain --manifest-path "$manifest")
root=${root%/*}

status=0
for dir in "$root"/fuzz/corpus/preview_*; do
    if [ ! -d "$dir" ]; then
        printf 'FAIL no preview_* corpus in %s\n' "$root/fuzz/corpus"
        exit 1
    fi
    name=${dir##*/}
    if diff -r "$dir" "ffi/tests/corpus/$name"; then
        printf 'ok %s\n' "$name"
    else
        printf 'FAIL %s\n' "$name"
        status=1
    fi
done
exit "$status"
