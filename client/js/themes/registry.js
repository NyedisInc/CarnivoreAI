(function () {
    'use strict';

    var STORAGE_KEY = 'carnivore.theme';
    var DEFAULT_THEME_ID = 'carnivore';
    var THEME_PREFERENCE_FIELD = 'theme';
    var VARS_CACHE_KEY = 'carnivore.theme.vars';
    var SESSION_SCOPE_ID = 'terminal-container';

    var PREAUTH_THEME_ID_RE = /^[A-Za-z0-9_](?:[A-Za-z0-9._ -]{0,126}[A-Za-z0-9._-])?$/;

    var manifests = new Map();
    var activeGlobalId = DEFAULT_THEME_ID;
    var sessionPinnedThemeId = null;
    var activeTerminalThemeId = null;
    var activeSessionName = null;
    var xtermListeners = [];
    var initialized = false;
    var appliedCssVarValues = {};
    var sessionAppliedVarValues = {};
    var replayInProgress = false;
    var terminalScopePaintDeferred = false;

    function getStoredThemeId() {
        var bridge = globalThis.PreferenceBridge;
        if (bridge && typeof bridge.read === 'function') {
            var shared = bridge.read(THEME_PREFERENCE_FIELD, readLocalThemeId);
            if (shared && typeof shared === 'string') return shared;
            return DEFAULT_THEME_ID;
        }
        return readLocalThemeId();
    }

    function readLocalThemeId() {
        try {
            var migrate = window.BrowserStorageMigrate;
            var v = migrate
                ? migrate.readMigrating(STORAGE_KEY)
                : localStorage.getItem(STORAGE_KEY);
            return v && typeof v === 'string' ? v : DEFAULT_THEME_ID;
        } catch (_) {
            return DEFAULT_THEME_ID;
        }
    }

    var lastCachedThemeVarsJson = null;

    function cacheThemeVars(themeId, cssVars) {
        try {
            var json = JSON.stringify({ id: themeId, cssVars: cssVars || {} });
            if (json === lastCachedThemeVarsJson) return;
            var migrate = window.BrowserStorageMigrate;
            if (migrate) migrate.writeMigrating(VARS_CACHE_KEY, json);
            else localStorage.setItem(VARS_CACHE_KEY, json);
            lastCachedThemeVarsJson = json;
        } catch (_) {  }
    }

    function readCachedThemeVars(themeId) {
        try {
            var migrate = window.BrowserStorageMigrate;
            var raw = migrate
                ? migrate.readMigrating(VARS_CACHE_KEY)
                : localStorage.getItem(VARS_CACHE_KEY);
            if (!raw) return {};
            var parsed = JSON.parse(raw);
            if (!parsed || parsed.id !== themeId) return {};
            var vars = parsed.cssVars;
            if (!vars || typeof vars !== 'object' || Array.isArray(vars)) return {};
            return vars;
        } catch (_) {
            return {};
        }
    }

    function authHeaders() {
        var headers = { 'Accept': 'application/json' };
        try {
            if (window.Auth && typeof window.Auth.getAccessToken === 'function') {
                var tok = window.Auth.getAccessToken();
                if (tok) headers['Authorization'] = 'Bearer ' + tok;
            } else if (window.Auth && typeof window.Auth.getToken === 'function') {
                var tok2 = window.Auth.getToken();
                if (tok2) headers['Authorization'] = 'Bearer ' + tok2;
            }
        } catch (_) {  }
        return headers;
    }

    /* could not be read */
    async function fetchManifests() {
        var dedupe = window.BootFetchDedupe;
        return dedupe ? dedupe.run('themes:/api/v1/themes', {}, readManifests) : readManifests();
    }

    async function readManifests() {
        try {
            var res = await fetch('/api/v1/themes', {
                method: 'GET',
                headers: authHeaders(),
                cache: 'no-store',
                credentials: 'same-origin'
            });
            if (!res.ok) {
                console.warn('Themes: /api/v1/themes returned HTTP ' + res.status + ' - using fallback');
                return null;
            }
            var data = await res.json();
            if (!Array.isArray(data)) {
                console.warn('Themes: /api/v1/themes returned non-array - using fallback');
                return null;
            }
            return data;
        } catch (err) {
            console.warn('Themes: /api/v1/themes fetch failed - using fallback', err);
            return null;
        }
    }

    async function fetchStaticManifest(id) {
        if (typeof id !== 'string' || !PREAUTH_THEME_ID_RE.test(id)) return null;
        try {
            var res = await fetch('/static/css/themes/' + encodeURIComponent(id) + '/theme.json',
                { credentials: 'same-origin' });
            if (!res.ok) return null;
            var b = await res.json();
            var plain = function (o) { return o && typeof o === 'object' && !Array.isArray(o); };
            if (!plain(b) || !plain(b.cssVars) || !Object.keys(b.cssVars).length || b.id !== id) return null;
            return { id: id, name: typeof b.name === 'string' ? b.name : id, cssVars: b.cssVars,
                xterm: plain(b.xterm) ? b.xterm : {} };
        } catch (_) { return null; }
    }

    async function paintPreauthPalette(id) {
        var gen = manifestRetryGeneration;
        var m = await fetchStaticManifest(id);
        if (!m && id !== DEFAULT_THEME_ID) m = await fetchStaticManifest(DEFAULT_THEME_ID);
        if (!m || initialized || gen !== manifestRetryGeneration || getStoredThemeId() !== id) return;
        paintCssVars(m.cssVars);
        cacheThemeVars(m.id, m.cssVars);
    }

    async function loadManifests() {
        var rows = await fetchManifests();
        var fallback = rows === null ? await fetchStaticManifest(DEFAULT_THEME_ID) : null;
        manifests.clear();
        (rows || []).forEach(function (m) {
            if (m && typeof m.id === 'string') manifests.set(m.id, m);
        });
        if (!manifests.has(DEFAULT_THEME_ID)) {
            manifests.set(DEFAULT_THEME_ID, fallback ||
                { id: DEFAULT_THEME_ID, name: DEFAULT_THEME_ID, cssVars: {}, xterm: {} });
        }
        return rows !== null;
    }

    function paintCssVars(cssVars) {
        var rootStyle = document.documentElement.style;
        var applied = window.ThemeVarWriter
            ? window.ThemeVarWriter.applyVarDiff(rootStyle, appliedCssVarValues, cssVars)
            : null;
        if (applied) {
            appliedCssVarValues = applied.values;
            return;
        }
        console.error('[Themes] MISSING DEPENDENCY: window.ThemeVarWriter. ' +
            'Load client/js/theme-var-writer.js BEFORE this file.');
        var nextVars = cssVars || {};
        var nextNames = Object.keys(nextVars);
        var nextSet = new Set(nextNames);
        Object.keys(appliedCssVarValues).forEach(function (name) {
            if (!nextSet.has(name)) rootStyle.removeProperty(name);
        });
        var values = {};
        nextNames.forEach(function (name) {
            var v = String(nextVars[name]);
            try { rootStyle.setProperty(name, v); } catch (_) {  }
            values[name] = v;
        });
        appliedCssVarValues = values;
    }

    function fireXtermChange(xtermPalette) {
        xtermListeners.forEach(function (cb) {
            try { cb(xtermPalette); } catch (e) { console.error('Themes: xterm listener threw', e); }
        });
    }

    // -----------------------------------------------------------------------
    // -----------------------------------------------------------------------

    var loadedEffectsScripts = new Set();
    var activeEffectsModule = null;
    var activeEffectsThemeId = null;
    var pendingConsents = new Map();

    function showConsentModal(manifest, info) {
        var open = pendingConsents.get(manifest.id);
        if (open) return new Promise(function (resolve) { open.queue.push(resolve); });
        var entry = { queue: [], cancel: noopCancel };
        pendingConsents.set(manifest.id, entry);
        var changed = !!(info && info.changed);

        return new Promise(function (resolve) {
            var overlay = document.createElement('div');
            overlay.className = 'modal-overlay';
            overlay.setAttribute('data-modal', 'theme-effects-consent');
            overlay.style.zIndex = '10001';

            var safeName = String(manifest.name || manifest.id).replace(/[<>&"']/g, function (c) {
                return ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&#39;' })[c];
            });
            var message = changed
                ? ('the script in theme &ldquo;' + safeName + '&rdquo; has changed '
                    + 'since you allowed it. this is a different <code>effects.js</code> '
                    + 'to the one you approved.')
                : ('theme &ldquo;' + safeName + '&rdquo; ships a javascript module '
                    + '(<code>effects.js</code>) that will run in this page.');
            overlay.innerHTML = (
                '<div class="modal-content" role="dialog" aria-modal="true" aria-labelledby="theme-fx-title">' +
                '  <div class="modal-header" id="theme-fx-title">' +
                '    theme effects script' +
                '  </div>' +
                '  <div class="modal-body">' +
                '    <div class="modal-message">' + message + '</div>' +
                '    <div class="modal-description">' +
                '      allow it to run? always allow covers this exact script and ' +
                '      applies on every device. never applies everywhere too, and ' +
                '      allow once lasts until you reload.' +
                '    </div>' +
                '  </div>' +
                '  <div class="modal-footer">' +
                '    <button class="modal-btn modal-btn-secondary" data-action="never">never</button>' +
                '    <button class="modal-btn modal-btn-secondary" data-action="once">allow once</button>' +
                '    <button class="modal-btn modal-btn-primary" data-action="always">always allow</button>' +
                '  </div>' +
                '</div>'
            );

            var releaseTrap = function () {};

            function finish(decision) {
                try { document.body.removeChild(overlay); } catch (_) {}
                releaseTrap();
                releaseTrap = function () {};
                pendingConsents.delete(manifest.id);
                resolve(decision);
                entry.queue.forEach(function (r) {
                    try { r(decision); } catch (_) {}
                });
            }

            overlay.addEventListener('click', function (e) {
                var btn = e.target.closest('button[data-action]');
                if (!btn) return;
                finish(btn.getAttribute('data-action'));
            });

            entry.cancel = function () { finish('never'); };

            document.body.appendChild(overlay);
            // and the three
            if (window.ModalStack && typeof window.ModalStack.trap === 'function') {
                releaseTrap = window.ModalStack.trap(overlay, {});
            }
            var onceBtn = overlay.querySelector('button[data-action="once"]');
            if (onceBtn) { try { onceBtn.focus(); } catch (_) {} }
        });
    }

    function noopCancel() {}

    function cancelPendingConsent(themeId) {
        var targets = themeId ? [pendingConsents.get(themeId)] : Array.from(pendingConsents.values());
        var hit = targets.filter(Boolean);
        hit.forEach(function (entry) { entry.cancel(); });
        return hit.length > 0;
    }

    function effectsUrlFor(manifest) {
        var file = manifest.effects;
        if (!file || typeof file !== 'string') return null;
        if (file.indexOf('..') !== -1 || file.indexOf('/') !== -1) {
            console.warn('Themes: rejecting effects path with traversal/slash:', file);
            return null;
        }
        var base = (manifest.source === 'user')
            ? '/themes/'
            : '/static/css/themes/';
        return base + encodeURIComponent(manifest.id) + '/' + encodeURIComponent(file);
    }

    function injectEffectsScript(manifest) {
        if (loadedEffectsScripts.has(manifest.id)) return;
        var url = effectsUrlFor(manifest);
        if (!url) return;
        loadedEffectsScripts.add(manifest.id);
        import(url).then(function (mod) {
            var initFn = (mod && typeof mod.init === 'function')
                ? mod.init
                : (mod && mod.default && typeof mod.default.init === 'function')
                    ? mod.default.init
                    : null;
            if (!initFn) {
                console.warn('Themes: effects module for', manifest.id, 'has no init() export');
                return;
            }
            var stillAllowed = true;
            var consent = globalThis.ThemeConsent;
            if (consent && typeof consent.entryFor === 'function') {
                var entry = consent.entryFor(manifest.id);
                if (entry && entry.decision === consent.DECISION_NEVER) stillAllowed = false;
            }
            if (!stillAllowed) {
                console.warn('Themes: effects refused mid-load for', manifest.id,
                    '- it was revoked before it started');
                loadedEffectsScripts.delete(manifest.id);
                return;
            }
            try {
                initFn({ themeContext: { id: manifest.id, manifest: manifest } });
                if (activeGlobalId !== manifest.id) {
                    try {
                        if (mod && typeof mod.destroy === 'function') mod.destroy();
                        else if (mod && mod.default && typeof mod.default.destroy === 'function') mod.default.destroy();
                    } catch (e2) {
                        console.warn('Themes: stale effects destroy() threw for', manifest.id, e2);
                    }
                    loadedEffectsScripts.delete(manifest.id);
                    return;
                }
                var destroyableMod = (mod && typeof mod.destroy === 'function')
                    ? mod
                    : (mod && mod.default && typeof mod.default.destroy === 'function')
                        ? mod.default
                        : null;
                activeEffectsModule = destroyableMod;
                activeEffectsThemeId = manifest.id;
                console.log('Themes: effects loaded for', manifest.id, '→', url);
            } catch (e) {
                console.warn('Themes: effects init() threw for', manifest.id, e);
            }
        }).catch(function (err) {
            loadedEffectsScripts.delete(manifest.id);
            console.warn('Themes: effects.js failed to load for', manifest.id, url, err);
        });
    }

    async function maybeLoadEffects(manifest) {
        if (!manifest || !manifest.effects) return;
        if (loadedEffectsScripts.has(manifest.id)) return;

        var consent = globalThis.ThemeConsent;
        if (!consent || typeof consent.gateEffects !== 'function') {
            console.warn('Themes: consent gate unavailable, skipping effects for', manifest.id);
            return;
        }
        await consent.gateEffects({
            manifest: manifest,
            inject: injectEffectsScript,
            prompt: showConsentModal,
            notify: tellUserAboutConsent,
        });
    }

    function tellUserAboutConsent(message) {
        var fab = globalThis.FabMenu;
        if (!fab || typeof fab.notify !== 'function') return;
        fab.notify(message, 'error');
    }

    function revokeEffects(themeId) {
        if (!themeId) return { destroyed: false, promptCancelled: false };
        var promptCancelled = cancelPendingConsent(themeId);
        var destroyed = false;
        if (activeEffectsThemeId === themeId && activeEffectsModule) {
            try {
                if (typeof activeEffectsModule.destroy === 'function') {
                    activeEffectsModule.destroy();
                    destroyed = true;
                }
            } catch (e) {
                console.warn('Themes: revoked effects destroy() threw for', themeId, e);
            }
            activeEffectsModule = null;
            activeEffectsThemeId = null;
        }
        loadedEffectsScripts.delete(themeId);
        console.warn('Themes: effects revoked for ' + themeId
            + (destroyed
                ? ' - its teardown ran, but anything it already did to this page stands until a reload'
                : ' - nothing of it was running here'));
        return { destroyed: destroyed, promptCancelled: promptCancelled };
    }

    function setActiveSession(name) {
        activeSessionName = name || null;
        if (window.TerminalBackground
            && typeof window.TerminalBackground.setActiveSession === 'function') {
            window.TerminalBackground.setActiveSession(activeSessionName);
        }
    }

    function getActiveSession() {
        return activeSessionName;
    }

    function applyTheme(themeId, opts) {
        var m = manifests.get(themeId);
        if (!m) {
            console.warn('Themes.applyTheme: unknown theme id ' + themeId + ' - keeping current');
            return false;
        }
        if (activeEffectsModule && activeEffectsThemeId !== themeId) {
            try {
                if (typeof activeEffectsModule.destroy === 'function') {
                    activeEffectsModule.destroy();
                }
            } catch (e) {
                console.warn('Themes: previous effects destroy() threw for', activeEffectsThemeId, e);
            }
            loadedEffectsScripts.delete(activeEffectsThemeId);
            activeEffectsModule = null;
            activeEffectsThemeId = null;
        }
        document.documentElement.dataset.theme = themeId;
        paintCssVars(m.cssVars || {});
        activeGlobalId = themeId;
        if (m.cssVars && Object.keys(m.cssVars).length) cacheThemeVars(themeId, m.cssVars);

        if (opts && opts.persist === true) {
            var writeLocal = function () {
                try {
                    var migrate = window.BrowserStorageMigrate;
                    if (migrate) migrate.writeMigrating(STORAGE_KEY, themeId);
                    else localStorage.setItem(STORAGE_KEY, themeId);
                } catch (_) {  }
            };
            var bridge = globalThis.PreferenceBridge;
            if (bridge && typeof bridge.write === 'function') {
                bridge.write(THEME_PREFERENCE_FIELD, themeId, writeLocal)
                    .catch(function (e) {
                        console.warn('Themes: could not share the theme choice', e);
                    });
            } else {
                writeLocal();
            }
        }

        // opts.forXterm === true
        var forXterm = opts && Object.prototype.hasOwnProperty.call(opts, 'forXterm')
            ? opts.forXterm
            : undefined;
        var shouldFireXterm = forXterm === true
            || (forXterm === undefined && !activeTerminalThemeId);
        if (shouldFireXterm) {
            fireXtermChange(m.xterm || {});
        }

        if (m.effects) {
            maybeLoadEffects(m).catch(function (e) {
                console.warn('Themes: maybeLoadEffects rejected', e);
            });
        }
        return true;
    }

    function pinThemeForSession(sessionName, themeId) {
        try {
            var url = '/api/v1/sessions/' + encodeURIComponent(sessionName) + '/theme';
            var headers = authHeaders();
            headers['Content-Type'] = 'application/json';
            return fetch(url, {
                method: 'PATCH',
                headers: headers,
                credentials: 'same-origin',
                body: JSON.stringify({ theme_id: themeId })
            }).then(function (res) {
                if (!res.ok) {
                    console.warn('Themes.pinThemeForSession: HTTP ' + res.status + ' for ' + sessionName);
                }
                return res.ok;
            }).catch(function (err) {
                console.warn('Themes.pinThemeForSession: network error', err);
                return false;
            });
        } catch (err) {
            console.warn('Themes.pinThemeForSession: threw before fetch', err);
            return Promise.resolve(false);
        }
    }

    function applyGlobal(themeId) {
        if (activeSessionName) {
            if (!manifests.has(themeId)) {
                console.warn('Themes.applyGlobal: unknown theme id ' + themeId
                    + ' - keeping current');
                return false;
            }
            sessionPinnedThemeId = themeId;
            paintTerminalScope();
            pinThemeForSession(activeSessionName, themeId);
            return true;
        }
        return applyTheme(themeId, { persist: true });
    }

    function resolveTerminalThemeId(context) {
        var pin = context ? context.pinnedTheme : sessionPinnedThemeId;
        if (pin && manifests.has(pin)) {
            return pin;
        }
        return null;
    }

    function getSessionManifest(context) {
        var resolved = resolveTerminalThemeId(context || {});
        return manifests.get(resolved || getStoredThemeId())
            || manifests.get(activeGlobalId) || null;
    }

    function getActiveTerminalManifest() {
        var resolved = resolveTerminalThemeId();
        if (resolved && manifests.has(resolved)) return manifests.get(resolved);
        return manifests.get(activeGlobalId) || null;
    }

    function sessionScopeElement() {
        return document.getElementById(SESSION_SCOPE_ID);
    }

    function paintTerminalScope() {
        if (replayInProgress) {
            terminalScopePaintDeferred = true;
            console.log('Themes: replay in progress, terminal theme paint deferred');
            return null;
        }
        var themeId = resolveTerminalThemeId();
        if (!themeId) {
            stripTerminalScope();
            return null;
        }
        var m = manifests.get(themeId);
        var el = sessionScopeElement();
        if (el) {
            el.dataset.sessionTheme = themeId;

            var nextVars = (m && m.cssVars) || {};
            var applied = window.ThemeVarWriter
                ? window.ThemeVarWriter.applyVarDiff(el.style, sessionAppliedVarValues, nextVars)
                : null;
            var nextNames;
            if (applied) {
                sessionAppliedVarValues = applied.values;
                nextNames = Object.keys(applied.values);
            } else {
                console.error('[Themes] MISSING DEPENDENCY: window.ThemeVarWriter. ' +
                    'Load client/js/theme-var-writer.js BEFORE this file.');
                nextNames = Object.keys(nextVars);
                var nextSet = new Set(nextNames);
                Object.keys(sessionAppliedVarValues).forEach(function (name) {
                    if (!nextSet.has(name)) {
                        try { el.style.removeProperty(name); } catch (_) {  }
                    }
                });
                var values = {};
                nextNames.forEach(function (name) {
                    var v = String(nextVars[name]);
                    try { el.style.setProperty(name, v); } catch (_) {  }
                    values[name] = v;
                });
                sessionAppliedVarValues = values;
            }
            console.log('Themes: terminal theme ' + themeId + ' (' + nextNames.length + ' inline vars)');
        } else {
            console.warn('Themes: ' + SESSION_SCOPE_ID + ' not found - palette applied, CSS scope skipped');
        }

        activeTerminalThemeId = themeId;

        if (m && m.xterm) {
            fireXtermChange(m.xterm);
        }
        return themeId;
    }

    function applyScopeTo(el, context) {
        if (!el || !el.style) return function () {};
        var applied = {};
        function paint() {
            var m = getSessionManifest(context || {});
            if (m) el.dataset.sessionTheme = m.id;
            else if (el.dataset.sessionTheme) delete el.dataset.sessionTheme;
            var next = (m && m.cssVars) || {};
            if (!window.ThemeVarWriter) {
                console.error('[Themes] MISSING DEPENDENCY: window.ThemeVarWriter.');
                return;
            }
            applied = window.ThemeVarWriter.applyVarDiff(el.style, applied, next).values;
        }
        paint();
        var stop = onXtermThemeChange(paint);
        return function () {
            stop();
            if (window.ThemeVarWriter) {
                window.ThemeVarWriter.applyVarDiff(el.style, applied, {});
            }
            applied = {};
            if (el.dataset.sessionTheme) delete el.dataset.sessionTheme;
        };
    }

    function stripTerminalScope() {
        var el = sessionScopeElement();
        if (el) {
            if (el.dataset.sessionTheme) delete el.dataset.sessionTheme;
            Object.keys(sessionAppliedVarValues).forEach(function (name) {
                try { el.style.removeProperty(name); } catch (_) {  }
            });
        }
        sessionAppliedVarValues = {};
        activeTerminalThemeId = null;
        var g = manifests.get(activeGlobalId);
        if (g && g.xterm) fireXtermChange(g.xterm);
    }

    function applySessionScope(context) {
        var c = context || {};
        sessionPinnedThemeId = c.pinnedTheme || null;
        return paintTerminalScope();
    }

    function clearSession() {
        sessionPinnedThemeId = null;
        terminalScopePaintDeferred = false;
        stripTerminalScope();
    }

    function setReplayInProgress(flag) {
        var was = replayInProgress;
        replayInProgress = !!flag;
        if (was && !replayInProgress && terminalScopePaintDeferred) {
            terminalScopePaintDeferred = false;
            console.log('Themes: replay finished - painting the current terminal theme');
            paintTerminalScope();
        }
    }

    function getActiveGlobal() {
        return manifests.get(activeGlobalId) || null;
    }

    function listAll() {
        var rows = Array.from(manifests.values());
        rows.sort(function (a, b) {
            var aBuilt = (a.source === 'builtin') ? 0 : 1;
            var bBuilt = (b.source === 'builtin') ? 0 : 1;
            if (aBuilt !== bBuilt) return aBuilt - bBuilt;
            return (a.name || a.id).toLowerCase().localeCompare((b.name || b.id).toLowerCase());
        });
        return rows;
    }

    function onXtermThemeChange(cb) {
        if (typeof cb !== 'function') return function () {};
        xtermListeners.push(cb);
        return function () {
            var idx = xtermListeners.indexOf(cb);
            if (idx >= 0) xtermListeners.splice(idx, 1);
        };
    }

    function paintStoredGlobal() {
        var stored = getStoredThemeId();
        if (!manifests.has(stored)) {
            applyTheme(DEFAULT_THEME_ID, { persist: false });
            return DEFAULT_THEME_ID;
        }
        applyTheme(stored, { persist: false });
        try {
            var migrate = window.BrowserStorageMigrate;
            if (migrate) migrate.writeMigrating(STORAGE_KEY, stored);
            else localStorage.setItem(STORAGE_KEY, stored);
        } catch (_) {  }
        return stored;
    }

    var MANIFEST_RETRY_MAX = 5;
    var manifestRetryGeneration = 0;

    function scheduleManifestRetry(generation, attempt) {
        if (attempt >= MANIFEST_RETRY_MAX) return;
        var delay = Math.min(60000, 2000 * Math.pow(2, attempt));
        setTimeout(function () {
            if (generation !== manifestRetryGeneration) return;
            loadManifests().then(function (ok) {
                if (generation !== manifestRetryGeneration) return;
                if (!ok) {
                    scheduleManifestRetry(generation, attempt + 1);
                    return;
                }
                var nav = window.ThemeNavigation;
                if (nav && typeof nav.reapply === 'function') nav.reapply();
                else paintStoredGlobal();
            });
        }, delay);
    }

    var themesPushOff = null;

    function followThemesTopic(attempt) {
        if (themesPushOff) return;
        var push = globalThis.ResourcePush;
        if (!push || typeof push.onChange !== 'function') {
            if ((attempt || 0) < 5) setTimeout(function () { followThemesTopic((attempt || 0) + 1); }, 2000);
            return;
        }
        themesPushOff = push.onChange(function (topics) {
            if (!topics || topics.indexOf('themes') === -1) return;
            loadManifests().then(function (ok) {
                if (!ok) return;
                var nav = window.ThemeNavigation;
                if (nav && typeof nav.reapply === 'function') nav.reapply();
                else paintStoredGlobal();
            });
        });
    }

    async function init() {
        var generation = ++manifestRetryGeneration;
        var loaded = await loadManifests();
        paintStoredGlobal();
        followThemesTopic();
        if (!loaded) scheduleManifestRetry(generation, 0);
        initialized = true;
        console.log('Themes: initialized - ' + manifests.size + ' manifest(s), active=' + activeGlobalId);
    }

    window.Themes = {
        init: init,
        applyGlobal: applyGlobal,
        pinThemeForSession: pinThemeForSession,
        applyTheme: applyTheme,
        setActiveSession: setActiveSession,
        getActiveSession: getActiveSession,
        applySessionScope: applySessionScope,
        applyScopeTo: applyScopeTo,
        clearSession: clearSession,
        setReplayInProgress: setReplayInProgress,
        revokeEffects: revokeEffects,
        _showConsentModal: showConsentModal,
        getActiveGlobal: getActiveGlobal,
        getActiveTerminalManifest: getActiveTerminalManifest,
        getSessionManifest: getSessionManifest,
        resolveTerminalThemeId: resolveTerminalThemeId,
        listAll: listAll,
        onXtermThemeChange: onXtermThemeChange,
        STORAGE_KEY: STORAGE_KEY,
        DEFAULT_THEME_ID: DEFAULT_THEME_ID,
        getStoredThemeId: getStoredThemeId,
        applyStoredThemeIdSync: function () {
            var id = getStoredThemeId();
            document.documentElement.dataset.theme = id;
            var cached = readCachedThemeVars(id);
            paintCssVars(cached);
            if (!Object.keys(cached).length) paintPreauthPalette(id);
            return id;
        },
        get initialized() { return initialized; }
    };
})();
