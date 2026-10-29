/* <script */

(function () {
    'use strict';

    var STATUS_UNLOADED = 'unloaded';
    /** @type {string} A loadFamily() call is in flight. */
    var STATUS_LOADING = 'loading';
    /** @type {string} Every resource in the family executed successfully. */
    var STATUS_LOADED = 'loaded';
    /** @type {string} The most recent attempt failed; the next call retries. */
    var STATUS_FAILED = 'failed';

    /** @type {number} Retries per resource before that resource gives up. */
    var DEFAULT_MAX_RETRIES = 2;
    /** @type {number} Base backoff between retries, multiplied by attempt #. */
    var DEFAULT_RETRY_DELAY_MS = 300;

    var _families = {};

    /* <script */
    function _loadOneScript(url, maxRetries, retryDelayMs) {
        return new Promise(function (resolve) {
            var attempts = 0;
            var script = document.createElement('script');
            script.src = url;
            script.async = false;

            function cleanup() {
                script.removeEventListener('load', onLoad);
                script.removeEventListener('error', onError);
            }

            function onLoad() {
                cleanup();
                resolve({ ok: true, url: url, attempts: attempts });
            }

            function onError() {
                attempts += 1;
                if (attempts <= maxRetries) {
                    setTimeout(function () {
                        var sep = url.indexOf('?') === -1 ? '?' : '&';
                        script.src = url + sep + '_retry=' + attempts;
                    }, retryDelayMs * attempts);
                    return;
                }
                cleanup();
                resolve({ ok: false, url: url, attempts: attempts });
            }

            script.addEventListener('load', onLoad);
            script.addEventListener('error', onError);
            document.head.appendChild(script);
        });
    }

    /* could not */
    function loadFamily(name, urls, opts) {
        var existing = _families[name];
        if (existing && existing.status === STATUS_LOADED) {
            return Promise.resolve({ ok: true, name: name, cached: true });
        }
        if (existing && existing.status === STATUS_LOADING && existing.promise) {
            return existing.promise;
        }

        var o = opts || {};
        var maxRetries = typeof o.maxRetries === 'number' ? o.maxRetries : DEFAULT_MAX_RETRIES;
        var retryDelayMs = typeof o.retryDelayMs === 'number' ? o.retryDelayMs : DEFAULT_RETRY_DELAY_MS;

        var perScript = urls.map(function (url) {
            return _loadOneScript(url, maxRetries, retryDelayMs);
        });

        var promise = Promise.all(perScript).then(function (results) {
            var failed = results.filter(function (r) { return !r.ok; });
            if (failed.length > 0) {
                _families[name] = { status: STATUS_FAILED, promise: null };
                var names = failed.map(function (r) { return r.url; });
                throw new Error(
                    'module family "' + name + '" failed to load: ' +
                    names.join(', ')
                );
            }
            _families[name] = { status: STATUS_LOADED, promise: promise };
            return { ok: true, name: name, cached: false };
        });

        _families[name] = { status: STATUS_LOADING, promise: promise };
        return promise;
    }

    function status(name) {
        var f = _families[name];
        return f ? f.status : STATUS_UNLOADED;
    }

    window.ModuleLoader = {
        loadFamily: loadFamily,
        status: status,
        STATUS_UNLOADED: STATUS_UNLOADED,
        STATUS_LOADING: STATUS_LOADING,
        STATUS_LOADED: STATUS_LOADED,
        STATUS_FAILED: STATUS_FAILED
    };
})();
