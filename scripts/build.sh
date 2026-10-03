#!/bin/sh
set -eu

cd -- "$(dirname "$0")/.."
xcodegen generate
xcodebuild -project BrushesQuickLook.xcodeproj -scheme BrushesQuickLook \
    -configuration Release ONLY_ACTIVE_ARCH=NO -derivedDataPath build.noindex -quiet build
