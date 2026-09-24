#!/bin/sh
set -eu

export PATH="$HOME/.cargo/bin:$PATH"
export MACOSX_DEPLOYMENT_TARGET
cd "$(dirname "$0")/.."

if ! command -v rustup >/dev/null 2>&1; then
    echo "error: rustup not found. Install rustup (https://rustup.rs) so the build uses the Rust version pinned in rust-toolchain.toml." >&2
    exit 1
fi
cargo=$(rustup which cargo)
PATH="${cargo%/*}:$PATH"

targets=
for arch in $ARCHS; do
    case "$arch" in
        arm64) targets="$targets aarch64-apple-darwin" ;;
        x86_64) targets="$targets x86_64-apple-darwin" ;;
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
    esac
done

set --
for target in $targets; do
    cargo build --release --manifest-path ffi/Cargo.toml --target "$target"
    set -- "$@" "ffi/target/$target/release/libbrushkit_ffi.a"
done

mkdir -p ffi/target/universal
lipo -create "$@" -output ffi/target/universal/libbrushkit_ffi.a
lipo -info ffi/target/universal/libbrushkit_ffi.a
