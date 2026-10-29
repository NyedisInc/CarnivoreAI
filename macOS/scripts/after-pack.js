'use strict';

const fs = require('node:fs');
const path = require('node:path');
const adhocSignHook = require('./adhoc-sign');
const { stagePayload, signPayload } = require('./payload-after-pack');

module.exports = async function afterPack(context) {
  let staged = null;
  if (context.electronPlatformName === 'darwin' && process.env.CARNIVORE_SKIP_PAYLOAD !== '1'
      && !/-(x64|arm64)-temp$/.test(path.basename(context.appOutDir))) {
    const appPath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
    if (!fs.existsSync(appPath)) {
      throw new Error(`afterPack: expected bundle not found at ${appPath}`);
    }
    for (const tree of stagePayload(appPath)) {
      console.log(`[payload] placed ${tree}`);
    }
    staged = appPath;
  }
  await adhocSignHook(context);
  if (staged) signPayload(staged, Boolean(context.packager.platformSpecificBuildOptions.identity));
};
