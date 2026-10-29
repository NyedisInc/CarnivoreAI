'use strict';


const PRODUCT_NAME = 'Carnivore';
const TMUX_SOCKET_NAME = 'carnivore';
const TMUX_SESSION_PREFIX = 'carnivore_';
const DB_FILENAME = 'carnivore.db';
const DB_BACKUP_PREFIX = 'carnivore.db.bak-v';
const STATE_DIR_NAME = 'Carnivore';
const MENUBAR_STATE_DIR_NAME = 'Carnivore Menubar';
const BUNDLE_ID = 'ai.carnivore.menubar';
const ENV_PREFIX = 'CARNIVORE_';
const UPLOAD_DIR_NAME = '.carnivore_uploads';
const BROWSER_KEY_PREFIX = 'carnivore.';
const RELEASE_REPO = 'NyedisInc/CarnivoreAI';
const LEGACY_MENUBAR_STATE_DIR_NAMES = ['cloude-code-menubar'];

module.exports = {
    PRODUCT_NAME,
    TMUX_SOCKET_NAME,
    TMUX_SESSION_PREFIX,
    DB_FILENAME,
    DB_BACKUP_PREFIX,
    STATE_DIR_NAME,
    MENUBAR_STATE_DIR_NAME,
    BUNDLE_ID,
    ENV_PREFIX,
    UPLOAD_DIR_NAME,
    BROWSER_KEY_PREFIX,
    RELEASE_REPO,
    LEGACY_MENUBAR_STATE_DIR_NAMES,
};
