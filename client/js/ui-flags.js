
console.log('[UIFlags Module] Loading...');

(function () {
    /** @type {string} The endpoint carrying the flags. */
    const FEATURES_PATH = '/features';

    const _flags = {
        show_mark_unread_control: true,
    };

    /** @type {Promise|null} The one in-flight or settled probe. */
    let _probe = null;

    function _apply(block) {
        if (!block || typeof block !== 'object') return;
        const keys = Object.keys(_flags);
        for (let i = 0; i < keys.length; i++) {
            const k = keys[i];
            if (typeof block[k] === 'boolean') _flags[k] = block[k];
        }
    }

    function ensure() {
        if (_probe) return _probe;
        if (!window.API || typeof window.API.call !== 'function') {
            _probe = Promise.resolve(_flags);
            return _probe;
        }
        _probe = window.API.call(FEATURES_PATH)
            .then(function (data) {
                _apply(data && data.ui);
                return _flags;
            })
            .catch(function (err) {
                console.warn('[UIFlags] flags left at their defaults: ' +
                             (err && err.message ? err.message : String(err)));
                return _flags;
            });
        return _probe;
    }

    function showMarkUnreadControl() {
        return _flags.show_mark_unread_control !== false;
    }

    const api = {
        ensure: ensure,
        showMarkUnreadControl: showMarkUnreadControl,
    };

    globalThis.UIFlags = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    console.log('[UIFlags Module] Loaded');
})();
