#!/bin/sh
set -eu

export PATH="$HOME/.cargo/bin:$PATH"
export MACOSX_DEPLOYMENT_TARGET
cd "$(dirname "$0")/.."

set --
for arch in $ARCHS; do
    case "$arch" in
        arm64) target=aarch64-apple-darwin ;;
        x86_64) target=x86_64-apple-darwin ;;
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
    esac
    cargo build --release --manifest-path ffi/Cargo.toml --target "$target"
    set -- "$@" "ffi/target/$target/release/libbrushkit_ffi.a"
done

mkdir -p ffi/target/universal
lipo -create "$@" -output ffi/target/universal/libbrushkit_ffi.a
lipo -info ffi/target/universal/libbrushkit_ffi.a
