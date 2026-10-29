#!/bin/bash

set -e

if ! command -v sips &> /dev/null; then
    echo "⚠️  sips not found (should be built into macOS)"
    exit 1
fi

if ! command -v iconutil &> /dev/null; then
    echo "⚠️  iconutil not found (should be built into macOS)"
    exit 1
fi

echo "🎨 Generating app icon bundle from AppIcon-1024.png..."

SOURCE="AppIcon-1024.png"

ICONSET="icon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"


echo "  Generating icon sizes..."

sips -z 16 16 "$SOURCE" --out "$ICONSET/icon_16x16.png" > /dev/null
sips -z 32 32 "$SOURCE" --out "$ICONSET/icon_16x16@2x.png" > /dev/null

sips -z 32 32 "$SOURCE" --out "$ICONSET/icon_32x32.png" > /dev/null
sips -z 64 64 "$SOURCE" --out "$ICONSET/icon_32x32@2x.png" > /dev/null

sips -z 128 128 "$SOURCE" --out "$ICONSET/icon_64x64@2x.png" > /dev/null

sips -z 128 128 "$SOURCE" --out "$ICONSET/icon_128x128.png" > /dev/null
sips -z 256 256 "$SOURCE" --out "$ICONSET/icon_128x128@2x.png" > /dev/null

sips -z 256 256 "$SOURCE" --out "$ICONSET/icon_256x256.png" > /dev/null
sips -z 512 512 "$SOURCE" --out "$ICONSET/icon_256x256@2x.png" > /dev/null

sips -z 512 512 "$SOURCE" --out "$ICONSET/icon_512x512.png" > /dev/null
sips -z 1024 1024 "$SOURCE" --out "$ICONSET/icon_512x512@2x.png" > /dev/null

echo "  ✅ Generated all icon sizes"

echo "  Converting to .icns..."
iconutil -c icns "$ICONSET" -o icon.icns

rm -rf "$ICONSET"

echo "✅ App icon created: icon.icns"
echo ""
echo "📦 Ready to build app with: npm run build"
