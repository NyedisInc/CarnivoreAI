
console.log('[PreferencesTransport Module] Loading...');

(function () {
    /** @type {string} The frame type this module answers. */
    const CHANGED = 'preferences.changed';

    function handleFrame(frame) {
        if (!globalThis.Preferences) return false;
        if (!frame || frame.type !== CHANGED) return false;
        return globalThis.Preferences.applyRemote(frame);
    }

    function refreshOnReconnect(api) {
        if (!globalThis.Preferences) return;
        const client = api || globalThis.API;
        Promise.resolve(globalThis.Preferences.hydrate(client)).then(function () {
            if (globalThis.MotionSetting) globalThis.MotionSetting.apply();
            if (globalThis.TerminalOptionMeta) globalThis.TerminalOptionMeta.apply();
            if (globalThis.TerminalScreenReader) globalThis.TerminalScreenReader.apply();
        }).catch(function (err) {
            console.warn('[Preferences] refresh on reconnect failed',
                err && err.message ? err.message : err);
        });
    }

    const api = {
        CHANGED: CHANGED,
        handleFrame: handleFrame,
        refreshOnReconnect: refreshOnReconnect,
    };

    globalThis.PreferencesTransport = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    console.log('[PreferencesTransport Module] Loaded');
})();
