const path = require('path');
const fs = require('fs');

function applyDevDockIcon({ app, nativeImage, platform = process.platform, iconPath = path.join(__dirname, 'assets', 'AppIcon-1024.png'), log = console }) {
  if (platform !== 'darwin' || app.isPackaged || !app.dock) return false;
  try {
    const image = fs.existsSync(iconPath) ? nativeImage.createFromPath(iconPath) : null;
    if (!image || image.isEmpty()) {
      log.warn('[dock] dev dock icon not loaded:', iconPath);
      return false;
    }
    app.dock.setIcon(image);
    return true;
  } catch (err) {
    log.warn('[dock] could not set the dev dock icon:', err.message);
    return false;
  }
}

module.exports = { applyDevDockIcon };
