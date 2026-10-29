# Menu Bar Icon Assets

This directory contains the menu bar icon for the Cloude Code macOS app.

## Icon Requirements

- **Format**: PNG with transparency
- **Style**: Monochrome (black on transparent), template image
- **Sizes**:
  - `iconTemplate.png` - 22x22px (standard DPI)
  - `iconTemplate@2x.png` - 44x44px (Retina/HiDPI)
  - `icon.icns` - macOS app icon bundle (for DMG installer)

## Design Guidelines

Menu bar icons should be:
- Simple and recognizable at small sizes
- Monochrome black (#000000) on transparent background
- Template images (will auto-adapt to light/dark mode)
- Avoid fine details that won't be visible at 22px

## Suggested Icon Design

A simple cloud with a terminal/command prompt symbol:
```
   ☁️  +  >_
(cloud) + (terminal)
```

## Generating Icons

### Manual Design

1. Create your icon in a vector graphics editor (Sketch, Figma, Illustrator)
2. Export as PNG at required sizes
3. Ensure black (#000000) on transparent background
4. Save as `iconTemplate.png` and `iconTemplate@2x.png`

### Online Tools

- [Cloudconvert](https://cloudconvert.com/) - Convert SVG to PNG
- [Icon Slate](https://www.kodlian.com/apps/icon-slate) - Create .icns bundles

## Converting to .icns

```bash
# Create iconset folder
mkdir icon.iconset

# Copy and resize your icon to various sizes
# (sizes: 16, 32, 64, 128, 256, 512, 1024)
sips -z 16 16 iconTemplate.png --out icon.iconset/icon_16x16.png
sips -z 32 32 iconTemplate.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32 iconTemplate.png --out icon.iconset/icon_32x32.png
# ... (repeat for all sizes)

# Convert to .icns
iconutil -c icns icon.iconset -o icon.icns
```

## Current Status

Currently using placeholder/empty icons. The app will work but show a blank menu bar icon until you replace these files with actual icons.
