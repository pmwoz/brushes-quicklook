#!/bin/sh
set -eu

usage() {
    printf 'usage: scripts/bump-brushkit.sh [--dry-run] <tag>\n' >&2
    exit 1
}

fail() {
    printf 'FAIL %s\n' "$1" >&2
    exit 1
}

dry_run=
case ${1-} in
    --dry-run) dry_run=1; shift ;;
esac
[ $# -eq 1 ] || usage
tag=$1
# The tag is spliced into a sed replacement, so it must not carry sed syntax.
case $tag in
    '' | -* | *[!A-Za-z0-9._-]*) usage ;;
esac

cd "$(dirname "$0")/.."

line=$(grep '^brushkit-preview = ' ffi/Cargo.toml) || fail 'no brushkit-preview line in ffi/Cargo.toml'
url=$(printf '%s\n' "$line" | sed -n 's/.*git = "\([^"]*\)".*/\1/p')
current=$(printf '%s\n' "$line" | sed -n 's/.*tag = "\([^"]*\)".*/\1/p')
[ -n "$url" ] || fail 'no git URL on the brushkit-preview line in ffi/Cargo.toml'
[ -n "$current" ] || fail 'no tag on the brushkit-preview line in ffi/Cargo.toml'

git ls-remote --exit-code --tags "$url" "refs/tags/$tag" >/dev/null \
    || fail "tag $tag not found at $url"

if [ -n "$dry_run" ]; then
    printf 'brushkit %s -> %s\n' "$current" "$tag"
    printf 'edit ffi/Cargo.toml tag\n'
    printf 'cargo update -p brushkit-preview (ffi/Cargo.lock)\n'
    printf 'replace ffi/tests/corpus with upstream fuzz/corpus/preview_*\n'
    printf 'run scripts/check-corpus.sh\n'
    printf 'run cargo test\n'
    printf 'print README parser limits\n'
    exit 0
fi

sed "/^brushkit-preview = /s/tag = \"[^\"]*\"/tag = \"$tag\"/" ffi/Cargo.toml > ffi/Cargo.toml.tmp
mv ffi/Cargo.toml.tmp ffi/Cargo.toml

cargo update --manifest-path ffi/Cargo.toml -p brushkit-preview

metadata=$(cargo metadata --manifest-path ffi/Cargo.toml --format-version 1)
manifest=$(printf '%s\n' "$metadata" \
    | jq -r '.packages[] | select(.name == "brushkit-preview") | .manifest_path')
[ -n "$manifest" ] || fail 'brushkit-preview not found in cargo metadata'
root=$(cargo locate-project --workspace --message-format plain --manifest-path "$manifest")
upstream=${root%/*}/fuzz/corpus

for dir in "$upstream"/preview_*; do
    [ -d "$dir" ] || fail "no preview_* corpus in $upstream"
done
rm -rf ffi/tests/corpus
mkdir ffi/tests/corpus
cp -R "$upstream"/preview_* ffi/tests/corpus/

scripts/check-corpus.sh
cargo test --manifest-path ffi/Cargo.toml

limits=$(awk '/^Known limits inherited from the parser/ { p = 1 } p && /^$/ { exit } p { printf "%d: %s\n", NR, $0 }' README.md)
[ -n "$limits" ] || fail 'parser limits paragraph not found in README.md'
printf '\nCheck these README lines against brushkit %s:\n%s\n' "$tag" "$limits"
