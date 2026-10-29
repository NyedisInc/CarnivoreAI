(function () {
    'use strict';

    var DEFAULT_DIM = 0.90;

    var Contrast = window.TerminalBackgroundContrast;
    var TEXT_TARGET = Contrast.TEXT_TARGET;
    var ACCENT_TARGET = Contrast.ACCENT_TARGET;
    var contrastRatio = Contrast.contrastRatio;
    var composite = Contrast.composite;
    var worstRatio = Contrast.worstRatio;
    var minimumDim = Contrast.minimumDim;

    var Manifest = window.TerminalBackgroundManifest;
    var isSafeImageName = Manifest.isSafeImageName;
    var imageUrlFor = Manifest.imageUrlFor;
    var manifestForSession = Manifest.manifestForSession;

    var UPLOADED_URL = 'cloude:uploaded';

    var ACTIVE_SESSION_EVENT = 'cloude:terminal-background-session';

    var overrides = {};
    var uploadedUrls = {};
    var uploadedFetching = {};
    /* the bottom bar */
    var activeSession = null;
    var surfaces = [];
    var overridesLoaded = false;


    /* could not */
    function effectiveDim(requested, xtermTheme) {
        var floor = minimumDim(xtermTheme);
        if (floor === null) return null;
        var want = (typeof requested === 'number' && isFinite(requested))
            ? requested
            : DEFAULT_DIM;
        return Math.min(1, Math.max(floor, Math.max(0, want)));
    }


    function resolveFor(sessionName, pinnedThemeId) {
        var none = { url: null, dim: DEFAULT_DIM, source: 'none', themeId: null };
        var themes = window.Themes;
        if (!themes || typeof themes.getActiveTerminalManifest !== 'function') {
            return none;
        }
        var override = (sessionName && overrides[sessionName]) || null;
        var requestedDim = (override && typeof override.dim === 'number')
            ? override.dim
            : null;

        if (override && override.disabled) {
            return { url: null, dim: requestedDim === null ? DEFAULT_DIM : requestedDim,
                source: 'none', themeId: null };
        }

        if (override && override.image) {
            if (isSafeImageName(override.image)) {
                return {
                    url: UPLOADED_URL,
                    dim: requestedDim === null ? DEFAULT_DIM : requestedDim,
                    source: 'upload',
                    themeId: null
                };
            }
            console.warn('TerminalBackground: refusing stored image name for '
                + sessionName + ':', override.image);
        }

        if (override && override.theme_id && typeof themes.listAll === 'function') {
            var all = themes.listAll() || [];
            for (var i = 0; i < all.length; i++) {
                if (all[i].id !== override.theme_id) continue;
                var borrowedUrl = imageUrlFor(all[i]);
                if (!borrowedUrl) break;
                return {
                    url: borrowedUrl,
                    dim: requestedDim === null
                        ? (all[i].background.dim != null
                            ? all[i].background.dim : DEFAULT_DIM)
                        : requestedDim,
                    source: 'session',
                    themeId: all[i].id
                };
            }
        }

        var manifest = manifestForSession(pinnedThemeId);
        var url = imageUrlFor(manifest);
        if (!url) {
            return { url: null, dim: requestedDim === null ? DEFAULT_DIM : requestedDim,
                source: 'none', themeId: null };
        }
        var themeDim = (manifest.background.dim != null)
            ? manifest.background.dim : DEFAULT_DIM;
        return {
            url: url,
            dim: requestedDim === null ? themeDim : requestedDim,
            source: 'theme',
            themeId: manifest.id
        };
    }



    function registerSurface(client) {
        if (!client) return false;
        for (var i = 0; i < surfaces.length; i++) {
            if (surfaces[i].client === client) return false;
        }
        surfaces.push({ client: client, pinnedThemeId: null });
        repaint();
        return true;
    }

    function unregisterSurface(client) {
        for (var i = 0; i < surfaces.length; i++) {
            if (surfaces[i].client !== client) continue;
            var host = hostOf(client);
            if (host && host.style) host.style.backgroundImage = '';
            surfaces.splice(i, 1);
            releaseUnusedUploads();
            return true;
        }
        return false;
    }

    function setSurfaceTheme(client, pinnedThemeId) {
        var id = pinnedThemeId || null;
        for (var i = 0; i < surfaces.length; i++) {
            if (surfaces[i].client !== client) continue;
            if (surfaces[i].pinnedThemeId === id) return false;
            surfaces[i].pinnedThemeId = id;
            repaint();
            return true;
        }
        return false;
    }

    /* padding */
    function hostOf(client) {
        try {
            var el = (client && typeof client._containerEl === 'function')
                ? client._containerEl() : null;
            if (!el) return null;
            if (typeof el.closest === 'function') {
                var outer = el.closest('.terminal-container');
                if (outer) return outer;
            }
            return el;
        } catch (_) { return null; }
    }

    function sessionOf(client) {
        try {
            var name = (client && typeof client._currentTmuxName === 'function')
                ? client._currentTmuxName() : null;
            var info = (client && client._currentSession) || null;
            return window.SessionKey ? window.SessionKey.forName(name, info && info.host_key) : name;
        } catch (_) { return null; }
    }

    function repaint() {
        var activeResolution = { url: null, dim: DEFAULT_DIM, source: 'none', themeId: null };
        for (var i = 0; i < surfaces.length; i++) {
            var painted = paintSurface(surfaces[i]);
            if (painted && painted.session && painted.session === activeSession) {
                activeResolution = painted.resolution;
            }
        }
        if (activeSession && !sessionIsPainted(activeSession)) {
            activeResolution = resolveFor(activeSession, activeThemeHint());
        }
        releaseUnusedUploads();
        return activeResolution;
    }

    function sessionIsPainted(name) {
        for (var i = 0; i < surfaces.length; i++) {
            if (sessionOf(surfaces[i].client) === name) return true;
        }
        return false;
    }

    function activeThemeHint() {
        for (var i = 0; i < surfaces.length; i++) {
            if (sessionOf(surfaces[i].client) === activeSession) {
                return surfaces[i].client._cellThemeManifest?.()?.id || surfaces[i].pinnedThemeId;
            }
        }
        return null;
    }

    function paintSurface(entry) {
        var client = entry.client;
        var host = hostOf(client);
        var session = sessionOf(client);
        var themeId = client._cellThemeManifest?.()?.id || entry.pinnedThemeId;
        var resolution = resolveFor(session, themeId);
        var manifest = manifestForSession(themeId);
        if (window.TerminalMascot) window.TerminalMascot.sync(client, manifest);

        var dim = resolution.url
            ? effectiveDim(resolution.dim, manifest && manifest.xterm)
            : null;

        if (resolution.url && dim === null) {
            console.warn('TerminalBackground: palette unmeasurable for '
                + (manifest && manifest.id) + ' - painting no image');
        }
        var paintUrl = (resolution.url && dim !== null) ? resolution.url : null;

        if (paintUrl === UPLOADED_URL) {
            if (session && uploadedUrls[session]) {
                paintUrl = uploadedUrls[session];
            } else {
                paintUrl = null;
                fetchUploadedImage(session);
            }
        }

        // padding
        // padding
        var scrim = null;
        if (paintUrl) {
            var parse = window.TerminalBackgroundOpacity
                && window.TerminalBackgroundOpacity.parseCssColorChannels;
            var ch = parse ? parse(manifest && manifest.xterm && manifest.xterm.background) : null;
            if (ch) {
                scrim = 'rgba(' + ch.r + ', ' + ch.g + ', ' + ch.b + ', ' + dim + ')';
            }
        }
        if (paintUrl && !scrim) {
            console.warn('TerminalBackground: no scrim colour for '
                + (manifest && manifest.id) + ' - painting no image');
            paintUrl = null;
        }

        if (!host) return null;
        var next = paintUrl
            ? 'linear-gradient(' + scrim + ', ' + scrim + '), url("' + paintUrl + '")'
            : '';
        if (host.style && host.style.backgroundImage !== next) {
            host.style.backgroundImage = next;
        }
        try {
            if (paintUrl) {
                host.dataset.terminalBg = 'on';
            } else if (host.dataset) {
                delete host.dataset.terminalBg;
            }
        } catch (_) {  }

        var handle = client && client._xtermOpacity;
        if (handle && typeof handle.setImageAlpha === 'function') {
            handle.setImageAlpha(paintUrl ? dim : null);
        }
        return { session: session, resolution: resolution };
    }


    function releaseUploadedImage(name) {
        var url = uploadedUrls[name];
        if (url) {
            try {
                if (typeof URL !== 'undefined' && URL.revokeObjectURL) {
                    URL.revokeObjectURL(url);
                }
            } catch (_) {  }
        }
        delete uploadedUrls[name];
    }

    function releaseUnusedUploads() {
        var wanted = {};
        for (var i = 0; i < surfaces.length; i++) {
            var name = sessionOf(surfaces[i].client);
            if (name) wanted[name] = true;
        }
        var freed = 0;
        for (var held in uploadedUrls) {
            if (!Object.prototype.hasOwnProperty.call(uploadedUrls, held)) continue;
            if (wanted[held] || held === activeSession) continue;
            releaseUploadedImage(held);
            freed += 1;
        }
        return freed;
    }

    function fetchUploadedImage(name) {
        var api = window.API;
        if (!name || !api || typeof api.fetchSessionBackgroundImage !== 'function') {
            return;
        }
        if (uploadedFetching[name]) return;
        uploadedFetching[name] = true;
        api.fetchSessionBackgroundImage(name).then(function (blob) {
            delete uploadedFetching[name];
            if (!blob) {
                var entry = overrides[name];
                if (entry) delete entry.image;
                repaint();
                return;
            }
            releaseUploadedImage(name);
            if (typeof URL === 'undefined' || !URL.createObjectURL) return;
            uploadedUrls[name] = URL.createObjectURL(blob);
            repaint();
        }).catch(function (err) {
            delete uploadedFetching[name];
            console.warn('TerminalBackground: could not load the uploaded image', err);
        });
    }

    function uploadImage(name, file) {
        var api = window.API;
        if (!name || !file || !api
            || typeof api.uploadSessionBackgroundImage !== 'function') {
            return Promise.reject(new Error('no session, file or api'));
        }
        return api.uploadSessionBackgroundImage(name, file).then(function (entry) {
            overrides[name] = entry;
            releaseUploadedImage();
            repaint();
            return entry;
        });
    }

    function clearImage(name) {
        var api = window.API;
        if (!name || !api
            || typeof api.deleteSessionBackgroundImage !== 'function') {
            return Promise.reject(new Error('no session or api'));
        }
        return api.deleteSessionBackgroundImage(name).then(function () {
            var entry = overrides[name];
            if (entry) delete entry.image;
            releaseUploadedImage();
            repaint();
        });
    }


    function setActiveSession(name) {
        var next = name || null;
        var moved = next !== activeSession;
        activeSession = next;
        // already exists
        if (moved) {
            try {
                window.dispatchEvent(new CustomEvent(ACTIVE_SESSION_EVENT, {
                    detail: { session: activeSession }
                }));
            } catch (_) {  }
        }
        if (activeSession && !overridesLoaded) {
            overridesLoaded = true;
            loadOverrides();
        }
        repaint();
    }

    function getActiveSession() { return activeSession; }

    function getOverrides() { return overrides; }

    function loadOverrides() {
        var api = window.API;
        if (!api || typeof api.call !== 'function') {
            return Promise.resolve(overrides);
        }
        return api.call('/session-backgrounds').then(function (data) {
            overrides = (data && data.overrides) || {};
            if (data && typeof data.default_dim === 'number'
                && isFinite(data.default_dim)) {
                DEFAULT_DIM = data.default_dim;
                window.TerminalBackground.DEFAULT_DIM = DEFAULT_DIM;
            }
            repaint();
            return overrides;
        }).catch(function (err) {
            console.warn('TerminalBackground: could not load overrides', err);
            return overrides;
        });
    }

    function setOverride(name, patch) {
        var api = window.API;
        if (!name || !api || typeof api.call !== 'function') {
            return Promise.reject(new Error('no session or api'));
        }
        var body = {
            theme_id: patch && patch.theme_id ? patch.theme_id : null,
            dim: (patch && typeof patch.dim === 'number') ? patch.dim : null,
            disabled: !!(patch && patch.disabled)
        };
        return api.call('/sessions/' + encodeURIComponent(name) + '/background', {
            method: 'PATCH',
            body: body
        }).then(function (entry) {
            if (entry && (entry.theme_id || entry.dim != null || entry.disabled)) {
                overrides[name] = entry;
            } else {
                delete overrides[name];
            }
            repaint();
            return entry;
        });
    }

    if (window.Themes && typeof window.Themes.onXtermThemeChange === 'function') {
        window.Themes.onXtermThemeChange(function () { repaint(); });
    }

    function resolve() {
        return resolveFor(activeSession, activeThemeHint());
    }

    window.TerminalBackground = {
        DEFAULT_DIM: DEFAULT_DIM,
        TEXT_TARGET: TEXT_TARGET,
        ACCENT_TARGET: ACCENT_TARGET,
        contrastRatio: contrastRatio,
        worstRatio: worstRatio,
        composite: composite,
        isSafeImageName: isSafeImageName,
        minimumDim: minimumDim,
        effectiveDim: effectiveDim,
        imageUrlFor: imageUrlFor,
        resolve: resolve,
        resolveFor: resolveFor,
        repaint: repaint,
        registerSurface: registerSurface,
        unregisterSurface: unregisterSurface,
        setSurfaceTheme: setSurfaceTheme,
        setActiveSession: setActiveSession,
        getActiveSession: getActiveSession,
        getOverrides: getOverrides,
        loadOverrides: loadOverrides,
        setOverride: setOverride,
        uploadImage: uploadImage,
        clearImage: clearImage,
        UPLOADED_URL: UPLOADED_URL,
        ACTIVE_SESSION_EVENT: ACTIVE_SESSION_EVENT
    };
})();
