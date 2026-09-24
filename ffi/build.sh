#!/bin/sh
set -eu

# Xcode.app started from the Dock passes no user PATH. These are the rustup.rs and Homebrew install locations.
export PATH="$PATH:$HOME/.cargo/bin:/opt/homebrew/opt/rustup/bin:/usr/local/opt/rustup/bin"
export MACOSX_DEPLOYMENT_TARGET
cd "$(dirname "$0")/.."

if ! command -v rustup >/dev/null 2>&1; then
    echo "error: rustup not found on PATH ($PATH). Install rustup (https://rustup.rs or brew install rustup) so the build uses the Rust version pinned in rust-toolchain.toml." >&2
    exit 1
fi
# Prepend the toolchain directory, not just call its cargo, so the rustc that cargo runs is pinned too.
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
