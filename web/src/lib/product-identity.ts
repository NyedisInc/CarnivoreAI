
export const PRODUCT_NAME = 'Carnivore';
export const TMUX_SOCKET_NAME = 'carnivore';
export const TMUX_SESSION_PREFIX = 'carnivore_';
export const LEGACY_TMUX_SESSION_PREFIXES: readonly string[] = Object.freeze(['cloude_']);
export const DB_FILENAME = 'carnivore.db';
export const DB_BACKUP_PREFIX = 'carnivore.db.bak-v';
export const STATE_DIR_NAME = 'Carnivore';
export const MENUBAR_STATE_DIR_NAME = 'Carnivore Menubar';
export const BUNDLE_ID = 'ai.carnivore.menubar';
export const ENV_PREFIX = 'CARNIVORE_';
export const UPLOAD_DIR_NAME = '.carnivore_uploads';
export const BROWSER_KEY_PREFIX = 'carnivore.';
export const LEGACY_BROWSER_KEY_PREFIXES: readonly string[] = Object.freeze(['cloude.']);
export const RELEASE_REPO = 'NyedisInc/CarnivoreAI';

export function handleWithoutPrefix(name: string): string {
    for (const p of [TMUX_SESSION_PREFIX, ...LEGACY_TMUX_SESSION_PREFIXES]) {
        if (name.startsWith(p) && name.length > p.length) return name.slice(p.length);
    }
    return name;
}
