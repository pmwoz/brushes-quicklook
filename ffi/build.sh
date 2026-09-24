#!/bin/sh
set -eu

export PATH="$HOME/.cargo/bin:$PATH"
export MACOSX_DEPLOYMENT_TARGET
cd "$(dirname "$0")/.."

targets=
for arch in $ARCHS; do
    case "$arch" in
        arm64) targets="$targets aarch64-apple-darwin" ;;
        x86_64) targets="$targets x86_64-apple-darwin" ;;
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
    esac
done

if installed=$(rustup target list --installed 2>/dev/null); then
    missing=
    for target in $targets; do
        echo "$installed" | grep -qx "$target" || missing="$missing $target"
    done
    if [ -n "$missing" ]; then
        echo "error: Missing Rust target(s):$missing. Install with: rustup target add$missing" >&2
        exit 1
    fi
fi

set --
for target in $targets; do
    cargo build --release --manifest-path ffi/Cargo.toml --target "$target"
    set -- "$@" "ffi/target/$target/release/libbrushkit_ffi.a"
done

mkdir -p ffi/target/universal
lipo -create "$@" -output ffi/target/universal/libbrushkit_ffi.a
lipo -info ffi/target/universal/libbrushkit_ffi.a
