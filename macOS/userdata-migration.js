'use strict';


const fs = require('fs');
const os = require('os');
const path = require('path');
const {
  MENUBAR_STATE_DIR_NAME,
  LEGACY_MENUBAR_STATE_DIR_NAMES,
} = require('./product-identity');

const OPT_OUT_ENV_VAR = 'CARNIVORE_KEEP_LEGACY_USERDATA';

function relocateUserData(appModule) {
  const supportDir = path.join(os.homedir(), 'Library', 'Application Support');
  const newDir = path.join(supportDir, MENUBAR_STATE_DIR_NAME);
  const legacyDir = path.join(supportDir, LEGACY_MENUBAR_STATE_DIR_NAMES[0]);

  if (process.env[OPT_OUT_ENV_VAR]) {
    console.log(`[userdata] ${OPT_OUT_ENV_VAR} is set; staying on the legacy directory: ${legacyDir}`);
    appModule.setPath('userData', legacyDir);
    return { migrated: false, usingLegacyPath: true, dir: legacyDir };
  }

  const newExists = fs.existsSync(newDir);
  const legacyExists = fs.existsSync(legacyDir);

  if (newExists) {
    if (legacyExists) {
      console.log(`[userdata] both ${newDir} and ${legacyDir} exist; using the new one, leaving the legacy one in place`);
    }
    appModule.setPath('userData', newDir);
    return { migrated: false, usingLegacyPath: false, dir: newDir };
  }

  if (!legacyExists) {
    appModule.setPath('userData', newDir);
    return { migrated: false, usingLegacyPath: false, dir: newDir };
  }

  try {
    fs.renameSync(legacyDir, newDir);
    console.log(`[userdata] migrated ${legacyDir} -> ${newDir}`);
    appModule.setPath('userData', newDir);
    return { migrated: true, usingLegacyPath: false, dir: newDir };
  } catch (err) {
    console.warn(`[userdata] could not migrate ${legacyDir} -> ${newDir} (${err.message}); staying on the legacy directory`);
    appModule.setPath('userData', legacyDir);
    return { migrated: false, usingLegacyPath: true, dir: legacyDir };
  }
}

module.exports = { relocateUserData, OPT_OUT_ENV_VAR };
