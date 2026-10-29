
console.log('[ConfigEditorTreeState Module] Loading...');

(function () {
    const STORAGE_KEY = 'carnivore.configEditor.collapsed';

    const FORCE_COLLAPSED_DIRS = new Set(['plugins']);

    /** @type {?Object<string, boolean>} Lazily-read state map. */
    let cache = null;

    function load() {
        if (cache) return cache;
        try {
            const migrate = window.BrowserStorageMigrate;
            const raw = migrate
                ? migrate.readMigrating(STORAGE_KEY)
                : localStorage.getItem(STORAGE_KEY);
            cache = raw ? JSON.parse(raw) : {};
        } catch (err) {
            console.warn('ConfigEditorTreeState: failed to read collapsed-state:', err);
            cache = {};
        }
        return cache;
    }

    function setNodeCollapsed(key, collapsed) {
        const state = load();
        state[key] = collapsed;
        try {
            const migrate = window.BrowserStorageMigrate;
            const json = JSON.stringify(state);
            if (migrate) migrate.writeMigrating(STORAGE_KEY, json);
            else localStorage.setItem(STORAGE_KEY, json);
        } catch (err) {
            console.warn('ConfigEditorTreeState: failed to persist collapsed-state:', err);
        }
    }

    function startsCollapsed(rootId, node, fallbackExpanded) {
        if (FORCE_COLLAPSED_DIRS.has(node.name)) return true;
        const key = `${rootId}:${node.rel_path || '__root__'}`;
        const state = load();
        if (Object.prototype.hasOwnProperty.call(state, key)) return state[key];
        return fallbackExpanded === undefined ? true : !fallbackExpanded;
    }

    function isForcedCollapsed(name) {
        return FORCE_COLLAPSED_DIRS.has(name);
    }

    function collapseAllDirs(keys = []) {
        const state = load();
        for (const key of [...Object.keys(state), ...keys]) {
            if (!key.endsWith(':__root__')) state[key] = true;
        }
        try {
            const migrate = window.BrowserStorageMigrate;
            const json = JSON.stringify(state);
            if (migrate) migrate.writeMigrating(STORAGE_KEY, json);
            else localStorage.setItem(STORAGE_KEY, json);
        } catch (err) {
            console.warn('ConfigEditorTreeState: failed to persist collapsed-state:', err);
        }
    }

    window.ConfigEditorTreeState = {
        load, setNodeCollapsed, startsCollapsed, isForcedCollapsed, collapseAllDirs,
        STORAGE_KEY, FORCE_COLLAPSED_DIRS,
    };
    console.log('[ConfigEditorTreeState Module] Exported as window.ConfigEditorTreeState');
})();
