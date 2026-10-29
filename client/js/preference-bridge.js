
console.log('[PreferenceBridge Module] Loading...');

(function () {
    function read(field, localReader) {
        const local = () => {
            try {
                return localReader();
            } catch (err) {
                console.warn('[PreferenceBridge] local read failed for ' + field, err);
                return undefined;
            }
        };
        const prefs = globalThis.Preferences;
        if (!prefs || typeof prefs.get !== 'function') return local();
        if (typeof prefs.status === 'function' && prefs.status() !== prefs.HYDRATED) {
            return local();
        }
        const shared = prefs.get(field, undefined);
        if (shared === undefined || shared === null) return local();
        return shared;
    }

    function isShared(field) {
        const prefs = globalThis.Preferences;
        if (!prefs || typeof prefs.get !== 'function') return false;
        if (typeof prefs.status === 'function' && prefs.status() !== prefs.HYDRATED) {
            return false;
        }
        const shared = prefs.get(field, undefined);
        return shared !== undefined && shared !== null;
    }

    async function write(field, value, localWriter) {
        try {
            localWriter();
        } catch (err) {
            console.warn('[PreferenceBridge] local write failed for ' + field, err);
        }
        const prefs = globalThis.Preferences;
        if (!prefs || typeof prefs.set !== 'function') {
            return { status: 'local_only' };
        }
        try {
            return await prefs.set(field, value);
        } catch (err) {
            console.warn('[PreferenceBridge] shared save failed for ' + field, err);
            return { status: 'failed', detail: String(err && err.message ? err.message : err) };
        }
    }

    async function writeMany(entries) {
        const changes = {};
        entries.forEach(function (entry) {
            try {
                entry.localWriter();
            } catch (err) {
                console.warn('[PreferenceBridge] local write failed for ' + entry.field, err);
            }
            changes[entry.field] = entry.value;
        });
        const prefs = globalThis.Preferences;
        if (!prefs || typeof prefs.setMany !== 'function') {
            return { status: 'local_only' };
        }
        try {
            return await prefs.setMany(changes);
        } catch (err) {
            console.warn('[PreferenceBridge] shared save failed', err);
            return { status: 'failed', detail: String(err && err.message ? err.message : err) };
        }
    }

    function follow(field, apply) {
        const prefs = globalThis.Preferences;
        if (!prefs || typeof prefs.subscribe !== 'function') return function () {};
        return prefs.subscribe(function (name, value) {
            if (name !== field) return;
            try {
                apply(value);
            } catch (err) {
                console.warn('[PreferenceBridge] apply failed for ' + field, err);
            }
        });
    }

    const api = {
        read: read,
        write: write,
        writeMany: writeMany,
        isShared: isShared,
        follow: follow,
    };

    globalThis.PreferenceBridge = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    console.log('[PreferenceBridge Module] Loaded');
})();
