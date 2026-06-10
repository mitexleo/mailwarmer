#!/usr/bin/env bash
set -euo pipefail

VERSION="${GITHUB_REF_NAME#v}"
echo "Building Mail Warmer v${VERSION} for macOS..."

# 1. Ensure deps
pip install pyinstaller
brew list create-dmg 2>/dev/null || brew install create-dmg

# 2. Generate icon if not present
if [ ! -f "assets/icon.icns" ]; then
    echo "Generating icon.icns..."
    mkdir -p assets
    # Generate a 1024x1024 PNG from the SVG using Python + Pillow
    python3 -c "
import struct, zlib

def create_png(width, height, r, g, b):
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    header = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    raw = b''
    for y in range(height):
        raw += b'\x00'
        for x in range(width):
            raw += bytes([r, g, b])
    idat = chunk(b'IDAT', zlib.compress(raw))
    iend = chunk(b'IEND', b'')
    return header + ihdr + idat + iend

png = create_png(1024, 1024, 26, 35, 126)  # dark blue
with open('assets/icon_1024.png', 'wb') as f:
    f.write(png)
"
    mkdir -p MailWarmer.iconset
    for size in 16 32 128 256 512; do
        sips -z $size $size assets/icon_1024.png --out "MailWarmer.iconset/icon_${size}x${size}.png" >/dev/null 2>&1
        sips -z $((size*2)) $((size*2)) assets/icon_1024.png --out "MailWarmer.iconset/icon_${size}x${size}@2x.png" >/dev/null 2>&1
    done
    iconutil -c icns MailWarmer.iconset -o assets/icon.icns
    rm -rf MailWarmer.iconset assets/icon_1024.png
fi

# 3. Build .app with PyInstaller (CLI, no spec file — BUNDLE removed in PyInstaller 6.x)
echo "Running PyInstaller..."
pyinstaller --clean \
    --onefile --windowed \
    --name "MailWarmer" \
    --icon "assets/icon.icns" \
    --osx-bundle-identifier "dev.mueen.mailwarmer" \
    warmup.py warmup_core.py

# 4. Ad-hoc code sign (required for Apple Silicon to run without terminal)
echo "Code signing..."
codesign --deep --force --sign - "dist/MailWarmer.app"

# 5. Create .dmg
echo "Creating DMG..."
create-dmg \
    --volname "Mail Warmer ${VERSION}" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "MailWarmer.app" 175 190 \
    --hide-extension "MailWarmer.app" \
    --app-drop-link 425 190 \
    "MailWarmer-${VERSION}.dmg" \
    "dist/"

echo "Done: MailWarmer-${VERSION}.dmg"
