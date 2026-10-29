console.log('[Terminal Module] Loading...');

const DEFAULT_XTERM_THEME = {
    background: '#1e1e1e',
    foreground: '#d4d4d4',
    cursor: '#d4d4d4',
    black: '#000000',
    red: '#cd3131',
    green: '#0dbc79',
    yellow: '#e5e510',
    blue: '#2472c8',
    magenta: '#bc3fbc',
    cyan: '#11a8cd',
    white: '#e5e5e5',
    brightBlack: '#666666',
    brightRed: '#f14c4c',
    brightGreen: '#23d18b',
    brightYellow: '#f5f543',
    brightBlue: '#3b8eea',
    brightMagenta: '#d670d6',
    brightCyan: '#29b8db',
    brightWhite: '#ffffff'
};

class Terminal {
    constructor(options = {}) {
        /** @type {?(Element|function(): ?Element)} the xterm host. */
        this._host = options.container || null;
        /** @type {Object<string, function(): ?Element>} page chrome. */
        this._pageChrome = options.chrome || {};
        /** @type {object} per-instance collaborators, keyed by global name. */
        this._wiring = options.wiring || {};
        /** @type {?object} socket role flags, for the caller's own use. */
        this._role = options.role || null;
        /** @type {?string} the slot this client is drawn in; see _ownsInput. */
        this._inputOwner = options.inputOwner || null;
        /** @type {?object} the shared xterm options; see initTerminal. */
        this._xtermOptionsBase = options.xtermOptions || null;

        this.ws = null;
        this.term = null;
        this.fitAddon = null;
        this.sessionActive = false;

        this.reconnectAttempts = 0;
        this._attemptsSinceProgress = 0;
        this.reconnectTimeout = null;
        this.maxReconnectAttempts = 5;
        this.isReconnecting = false;
        this._socketEverOpened = false;
        this._bytesEverSeen = false;
        this._initOutcome = 'unknown';
        this._unreachableReported = false;

        this.keepaliveInterval = null;

        this.queue = [];
        this.flushing = false;
        this._queuedBytes = 0;
        this._writeInFlight = false;
        this._writeDrained = null;

        this.autoScrollEnabled = true;
        this._programmaticScrollLock = 0;

        this.lastSentCols = null;
        this.lastSentRows = null;

        this.detachSessionBtn = null;
        this.statusEl = null;

        this._reconnectByNameAttempted = false;

        this._authProbeAttempted = false;

        this._restartWatch = null;
        this._restartWatchActive = false;

        this._navToken = null;

        // reconnect to the SAME session
        this._connGen = null;
    }

    setInputOwner(slot) { this._inputOwner = slot || null; }

    _containerEl() {
        if (typeof this._host === 'function') return this._host() || null;
        return this._host || null;
    }

    _chrome(name) {
        const entry = this._pageChrome[name];
        if (typeof entry === 'function') return entry() || null;
        return entry || null;
    }

    _m(name) {
        return this._wiring[name] !== undefined ? this._wiring[name] : window[name];
    }

    _navCurrent(what) {
        if (!window.NavigationGeneration) return true;
        if (this._navToken == null) return true;
        return window.NavigationGeneration.keep(this._navToken, what);
    }

    _beginConnection(what) {
        if (this._m('TerminalInputBuffer')) this._m('TerminalInputBuffer').begin(this, what);
        else this._connGen = null;
        if (window.TerminalHistoryGate) window.TerminalHistoryGate.discard(this, 'a new connection begins');
        if (this._m('TerminalStartupNotice')) this._m('TerminalStartupNotice').clear();
        if (this._m('TerminalSizeVote')) this._m('TerminalSizeVote').clear(this);
    }

    _sendUserBytes(bytes) {
        if (window.TerminalInputOwnership
            && !window.TerminalInputOwnership.surfacePermits(this._inputOwner)) return false;
        if (this._m('TerminalInputBuffer')) return this._m('TerminalInputBuffer').send(this, bytes);
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
        this.ws.send(bytes);
        return true;
    }

    async init() {
        console.log('Terminal: Initializing xterm.js');

        this.detachSessionBtn = this._chrome('detachSessionBtn');
        this.statusEl = this._chrome('statusText');

        if (this.detachSessionBtn) {
            this.detachSessionBtn.addEventListener('click', () => this.detachSession());
        }

        await this.waitForXterm();
        if (this._disposed) return;
        this.initTerminal();
    }

    async waitForXterm() {
        if (window.TerminalReadiness) return window.TerminalReadiness.waitForXterm(Terminal);
        if (typeof window.Terminal === 'undefined' || window.Terminal === Terminal) {
            throw new Error('xterm.js did not load, and neither did terminal-readiness.js');
        }
    }

    initTerminal() {
        console.log('Terminal: Creating xterm Terminal instance', {
            windowTerminal: typeof window.Terminal,
            localTerminal: typeof Terminal,
            isXtermTerminal: window.Terminal !== Terminal
        });

        const XTerminal = window.Terminal;

        const initialXtermTheme =
            this._cellThemeManifest?.()?.xterm
            || (window.Themes && window.Themes.getActiveTerminalManifest
                && window.Themes.getActiveTerminalManifest()?.xterm)
            || (window.Themes && window.Themes.getActiveGlobal && window.Themes.getActiveGlobal()?.xterm)
            || DEFAULT_XTERM_THEME;

        if (!this._xtermOptionsBase) {
            throw new Error('Terminal: built with no xterm options, so '
                + 'terminal-client-factory.js is not what built it');
        }
        this.term = new XTerminal(
            Object.assign({}, this._xtermOptionsBase, { theme: initialXtermTheme }));

        if (window.Motion && window.Motion.bindCursorBlink) window.Motion.bindCursorBlink(this.term);
        if (window.TerminalOptionMeta) window.TerminalOptionMeta.bind(this.term);
        if (window.TerminalScreenReader) window.TerminalScreenReader.bind(this.term);
        this._xtermOpacity = window.TerminalBackgroundOpacity && window.TerminalBackgroundOpacity.attach(this.term);
        if (this._xtermOpacity) {
            this._xtermOpacity.apply(initialXtermTheme);
        } else if (window.TerminalBackgroundOpacity) {
            this.term.options.minimumContrastRatio =
                window.TerminalBackgroundOpacity.minimumContrastRatioForXtermTheme(initialXtermTheme);
        }
        if (window.TerminalBackground) window.TerminalBackground.registerSurface(this);
        console.log('Terminal: Terminal instance created', {
            term: this.term,
            hasLoadAddon: typeof this.term?.loadAddon,
            allMethods: this.term ? Object.getOwnPropertyNames(Object.getPrototypeOf(this.term)).filter(m => typeof this.term[m] === 'function').slice(0, 20) : []
        });

        if (typeof this.term.loadAddon !== 'function') {
            console.error('Terminal methods available:', Object.getOwnPropertyNames(Object.getPrototypeOf(this.term)));
            throw new Error(`Terminal instance has no loadAddon method. Available methods: ${Object.getOwnPropertyNames(Object.getPrototypeOf(this.term)).join(', ')}`);
        }

        this.fitAddon = new FitAddon.FitAddon();
        this.term.loadAddon(this.fitAddon);

        this._webglAddon = window.TerminalAddons
            ? window.TerminalAddons.loadWebgl(this.term, this) : null;
        if (window.TerminalAddons) window.TerminalAddons.loadUnicode11(this.term);
        else console.error('Terminal: terminal-addons.js missing, no WebGL and no Unicode 11');

        const hostEl = this._containerEl();
        if (window.VisibilityObserver) window.VisibilityObserver.during(() => this.term.open(hostEl));
        else this.term.open(hostEl);
        if (window.TerminalPaintGate) window.TerminalPaintGate.register(this);

        if (window.Themes && typeof window.Themes.onXtermThemeChange === 'function') {
            this._unsubscribeXtermTheme = window.Themes.onXtermThemeChange((newXtermTheme) => {
                if (this._cellThemeManifest) return;
                if (!this.term || !newXtermTheme) return;
                try {
                    if (this._xtermOpacity) {
                        this._xtermOpacity.apply(newXtermTheme);
                    } else {
                        this.term.options.theme = newXtermTheme;
                        this.term.options.minimumContrastRatio = window.TerminalBackgroundOpacity
                            ? window.TerminalBackgroundOpacity.minimumContrastRatioForXtermTheme(newXtermTheme)
                            : 1;
                    }
                } catch (e) {
                    console.warn('Terminal: failed to apply xterm theme', e);
                }
            });
        }

        this._applyKeyHandlers();


        this._applyPasteHandler();
        if (window.TerminalFileDrop) window.TerminalFileDrop.attach(this);
        this._applyImageAttachButton();

        this._applyTouchSelection();
        this._applySelectWhileScrolled(); // see terminal-select-scrolled.js

        this._applyTerminalTools();

        this.term.onData(data => {
            var isMouse = !!(window.TerminalInputKind
                && window.TerminalInputKind.isMouseReport(data));
            if (this._m('AltScreenScroll') && !isMouse) this._m('AltScreenScroll').noteUserInput();
            if (this._m('TerminalScroll') && !isMouse) this._m('TerminalScroll').pinToBottom(this.term);
            if (window.TerminalInputKind) data = window.TerminalInputKind.softKeyboardShortcut(data);
            if (this._sendUserBytes(new TextEncoder().encode(data))) {
                if (!isMouse) this._noteUserInputToSession(data);
            }
        });

        if (this._m('TerminalLayout')) {
            this._m('TerminalLayout').install(this);
        } else {
            console.error('Terminal: TerminalLayout missing - the terminal '
                + 'will not refit on rotate, keyboard or sidebar pin');
        }

        this.setupScrollListener();

        if (window.TerminalKeyboardReveal) {
            this._uninstallKeyboardReveal = window.TerminalKeyboardReveal.install(
                this.term, this._m('TerminalScroll'));
        }

        this.term.writeln('\x1b[1;32mCarnivore Terminal\x1b[0m');
        this.term.writeln('');
        if (window.TerminalInputKind && window.TerminalInputKind.isCoarsePointer()) this.term.writeln('\x1b[2;37mKeyboard shortcuts:\x1b[0m\r\n  ¥  = Newline (Enter)\r\n  €  = Tab\r\n  £  = Shift+Tab\r\n');
        this.term.writeln('Waiting for session...\n');
        if (window.TerminalLifecycle) window.TerminalLifecycle.announceCreated(this.term);
    }

    _applyKeyHandlers() {
        if (!this.term) return;
        this.term.attachCustomKeyEventHandler((ev) => {
            if (window.ClipboardTools && window.ClipboardTools.handleCopyChord(ev, this)) {
                return false;
            }
            if (ev.type === 'keydown' && ev.key === 'Enter' && ev.shiftKey &&
                !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
                ev.preventDefault();
                ev.stopPropagation();
                const bytes = new Uint8Array([0x1b, 0x0d]);
                console.log('[SHIFT-ENTER] sending ESC+CR (\\x1b\\r), bytes:', bytes);
                if (this._sendUserBytes(bytes)) this._noteUserInputToSession();
                return false;
            }
            return true;
        });
    }

    _writeSynthetic(data) {
        if (!data) return;
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(new TextEncoder().encode(data));
        }
    }

    _applyPasteHandler() {
        const container = this._containerEl();
        if (!container) return;
        container.addEventListener('paste', async (e) => {
            const ticket = window.TerminalInputOwnership
                ? window.TerminalInputOwnership.claim('paste') : null;
            const items = (e.clipboardData && e.clipboardData.items) || [];
            let fileItem = null;
            for (const item of items) {
                if (item.kind === 'file') {
                    fileItem = item;
                    break;
                }
            }
            if (!fileItem) return;

            e.preventDefault();
            e.stopPropagation();
            const blob = fileItem.getAsFile();
            if (!blob) return;

            await this._uploadAndInjectFile(blob, blob.name || '', ticket);
        }, true);
    }

    _applyImageAttachButton() {
        const input = this._chrome('fileInput');
        if (!input) return;

        if (window.ClipboardTools && typeof window.ClipboardTools.wireFileInput === 'function') {
            window.ClipboardTools.wireFileInput(this, input);
        }
    }

    _applyTouchSelection() {
        if (window.TouchSelect && typeof window.TouchSelect.init === 'function') {
            window.TouchSelect.init(this);
        }
    }

    _applySelectWhileScrolled() { const sel = this._m('TerminalSelectScrolled'); if (sel) sel.init(this.term && this.term.element && this.term.element.parentElement, () => this.term); if (window.TerminalHistoryScroll) window.TerminalHistoryScroll.attach(this); }

    _applyTerminalTools() {
        if (this._m('TerminalToolsMenu')) {
            this._m('TerminalToolsMenu').wire(this, this._chrome('fileInput'));
        }
    }

    async _uploadAndInjectFile(blob, filename, ticket) {
        if (!window.ClipboardTools || typeof window.ClipboardTools.uploadAndInject !== 'function') {
            this._showStatusPill('upload unavailable', 'error');
            return;
        }
        await window.ClipboardTools.uploadAndInject(this, blob, filename || '', ticket);
    }

    _showStatusPill(message, kind) {
        if (window.FabMenu && typeof window.FabMenu.notify === 'function') {
            window.FabMenu.notify(message, kind);
            return;
        }
        console.warn('[terminal] no FabMenu to report through:', message);
    }

    enqueue(bytes) {
        if (window.TerminalHistoryGate && window.TerminalHistoryGate.offer(this, bytes)) return;
        const policy = window.TerminalWriteQueue;
        if (policy) {
            const over = policy.overflowBytes(this._queuedBytes, bytes.length);
            if (over > 0) {
                const dropped = policy.shedFront(this.queue, over);
                this._queuedBytes -= dropped;
                if (this._queuedBytes < 0) this._queuedBytes = 0;
                const mark = new TextEncoder().encode(policy.dropMarker(dropped));
                this.queue.unshift(mark);
                this._queuedBytes += mark.length;
                console.warn('[terminal] shed', dropped, 'bytes of unwritten output');
            }
        }
        this.queue.push(bytes);
        this._queuedBytes += bytes.length;
        if (this.flushing) return;
        // there is nothing
        this.flushing = true;
        this.flush();
    }

    _releaseQueueForSwitch() {
        this.queue.length = 0;
        this._queuedBytes = 0;
        // teardown parked on a promise nobody can settle - a session
        if (this._writeDrained) {
            const orphan = this._writeDrained;
            this._writeDrained = null;
            orphan();
        }
        if (!this._writeInFlight) return Promise.resolve();
        return new Promise((resolve) => { this._writeDrained = resolve; });
    }

    flush() {
        if (!this.term) {
            this.flushing = false;
            console.warn('[terminal] flush with no terminal, holding',
                this._queuedBytes, 'bytes');
            return;
        }
        if (this._paintHeld) {
            this.flushing = false;
            return;
        }
        let total = 0;
        for (const c of this.queue) total += c.length;
        const merged = new Uint8Array(total);
        let o = 0;
        while (this.queue.length) {
            const c = this.queue.shift();
            merged.set(c, o);
            o += c.length;
        }
        const follow = this._m('TerminalScroll')
            ? this._m('TerminalScroll').shouldFollowOutput(this.term)
            : this.autoScrollEnabled;

        this._queuedBytes = 0;
        this._writeInFlight = true;
        this.term.write(merged, () => {
            this.flushing = false;
            this._writeInFlight = false;
            if (this._writeDrained) {
                const drained = this._writeDrained;
                this._writeDrained = null;
                drained();
            }

            if (follow && this.term) {
                this.term.scrollToBottom();
            }

            if (this.queue.length) {
                this.flushing = true;
                const wait = this._m('TerminalLayoutWait');
                if (wait) wait.nextFrameOrTimeout(wait.FRAME_TIMEOUT_MS).then(() => this.flush());
                else requestAnimationFrame(() => this.flush());
            }
        });
    }

    setupScrollListener() {
        const container = this._containerEl();
        if (this._m('AltScreenScroll')) {
            this._m('AltScreenScroll').init(() => this.term, (d) => this._writeSynthetic(d));
        }
        if (this._m('TerminalScroll') && container) {
            this._m('TerminalScroll').init(container, () => this.term);
        }
    }

    _forceScrollToBottom(holdMs = 400) {
        if (!this.term) return;
        this._programmaticScrollLock++;
        this.autoScrollEnabled = true;
        if (this._m('TerminalScroll')) this._m('TerminalScroll').pinToBottom(this.term);
        const pin = () => {
            if (!this.term) return;
            try { this.term.scrollToBottom(); } catch (_) {  }
            const root = this.term.element || this._containerEl();
            const vp = (root && typeof root.querySelector === 'function')
                ? root.querySelector('.xterm-viewport') : null;
            if (vp) vp.scrollTop = vp.scrollHeight;
        };
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                pin();
                setTimeout(pin, 50);
                setTimeout(pin, 150);
                setTimeout(() => {
                    pin();
                    this._programmaticScrollLock = Math.max(0, this._programmaticScrollLock - 1);
                }, holdMs);
            });
        });
    }

    isScrolledToBottom(viewport) {
        if (!viewport) return true;
        const threshold = 10;
        return (viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight) <= threshold;
    }

    scrollToBottomAndEnableAutoScroll() {
        if (!this.term) return;
        this.autoScrollEnabled = true;
        if (this._m('AltScreenScroll') && this._m('AltScreenScroll').exitTranscript()) return;
        if (this._m('TerminalScroll')) {
            this._m('TerminalScroll').pinToBottom(this.term);
        } else {
            this.term.scrollToBottom();
        }
    }

    sendResize(source = 'unknown', force = false) {
        if (!(this.ws && this.ws.readyState === WebSocket.OPEN && this.term)) { console.warn(`[TERM-RESIZE] not delivered: no session attached, source=${source}`); return { delivered: false, reason: 'no-session' }; }

        const { cols, rows } = this._m('TerminalSizeVote') ? this._m('TerminalSizeVote').voteGrid(this) : this.term;

        if (!force && cols === this.lastSentCols && rows === this.lastSentRows) {
            return { delivered: false, reason: 'unchanged', cols, rows };
        }

        const frame = { type: 'pty_resize', cols, rows };
        if (this._m('TerminalSizeVote') && this._m('TerminalSizeVote').isWithdrawn(this, document)) frame.hidden = true;
        this.ws.send(JSON.stringify(frame));

        console.log(`[TERM-RESIZE] ${cols}x${rows} source=${source} ${window.TerminalMetrics && window.TerminalMetrics.describeCellMetrics ? window.TerminalMetrics.describeCellMetrics(this) : ''}`);

        this.lastSentCols = cols;
        this.lastSentRows = rows;
        return { delivered: true, cols, rows };
    }

    sendKeyToTerminal(keyData) {
        if (this._m('AltScreenScroll')) this._m('AltScreenScroll').noteUserInput();
        this._noteUserInputToSession(keyData);
        if (!this._sendUserBytes(new TextEncoder().encode(keyData))) {
            console.warn('Terminal: key not delivered, the pane is not ready');
        }
    }

    async connectToSession(session, opts = {}, ctx = {}) {
        const { initialScrollbackB64 = '', fifoStartOffset = null } = opts;
        this._navToken = (ctx && ctx.nav != null) ? ctx.nav
            : (window.NavigationGeneration ? window.NavigationGeneration.current() : null);
        this._beginConnection('connectToSession');
        console.log('Terminal: Connecting to session:', this._unwrapSession(session).id, {
            adopted: !!initialScrollbackB64,
            fifoStartOffset,
        });
        const paintPlan = window.TerminalReconnectBuffer ? window.TerminalReconnectBuffer.planFor(this.term, this._unwrapSession(this._currentSession).id, this._unwrapSession(session).id, initialScrollbackB64) : 'replace';

        if (this.ws) {
            try {
                this._intentionalClose = true;
                this.ws.close();
            } catch (e) {
                console.warn('Terminal: error closing prior WS:', e);
            }
            this.ws = null;
        }
        if (this.term && paintPlan !== 'keep') {
            await this._releaseQueueForSwitch();
            if (this._disposed || !this.term) return;
            try {
                this.term.reset();
            } catch (e) {
                console.warn('Terminal: xterm reset failed:', e);
            }
            this._applyKeyHandlers();
        }
        this._currentSession = null;
        this.sessionActive = false;
        this._resetRetryBudget('new session bound');

        this._currentSession = session;

        this.sessionActive = true;

        if (this.detachSessionBtn) this.detachSessionBtn.disabled = false;

        if (paintPlan === 'keep') { this._pendingPostConnectScroll = true; } else if (initialScrollbackB64) {
            if (await this._paintCapturedScreen(initialScrollbackB64, 'adopt') === 'painted') {
                this._needsReplayCtrlL = true;
                this._pendingPostConnectScroll = true;
            }
        } else {
            this.term.writeln('\x1b[1;32m[Session created - connecting to WebSocket...]\x1b[0m');
        }

        await this._connectWhenReady('scheduled connect');
    }

    async _connectWhenReady(what) {
        if (this._disposed || !this.term || !this._navCurrent(what)) return;
        await this.connectWebSocket();
    }

    async _paintCapturedScreen(b64, what) {
        if (!window.TerminalScrollbackPaint) {
            console.warn('Terminal: no scrollback paint module, skipping the capture');
            return 'nothing';
        }
        return window.TerminalScrollbackPaint.paint(this, b64, what);
    }

    async reconnectToExistingSession(session, ctx = {}) {
        if (this._disposed || !this.term) return;
        console.log('Terminal: Reconnecting to existing session:', this._unwrapSession(session).id);
        this._navToken = (ctx && ctx.nav != null) ? ctx.nav
            : (window.NavigationGeneration ? window.NavigationGeneration.current() : null);
        this._beginConnection('reconnectToExistingSession');
        const paintPlan = window.TerminalReconnectBuffer ? window.TerminalReconnectBuffer.planFor(this.term, this._unwrapSession(this._currentSession).id, this._unwrapSession(session).id, session && session.initial_scrollback_b64) : 'replace';

        if (this.ws) {
            try {
                this._intentionalClose = true;
                this.ws.close();
            } catch (e) {
                console.warn('Terminal: error closing prior WS:', e);
            }
            this.ws = null;
        }
        if (this.term && paintPlan !== 'keep') {
            await this._releaseQueueForSwitch();
            if (this._disposed || !this.term) return;
            try {
                this.term.reset();
            } catch (e) {
                console.warn('Terminal: xterm reset failed:', e);
            }
            this._applyKeyHandlers();
        }
        this._currentSession = null;
        this.sessionActive = false;
        this._resetRetryBudget('new session bound');

        this._currentSession = session;
        this.sessionActive = true;

        if (this.detachSessionBtn) {
            this.detachSessionBtn.disabled = false;
        }

        const initialScrollbackB64 = session && session.initial_scrollback_b64;
        if (paintPlan === 'keep') { this._pendingPostConnectScroll = true; } else if (initialScrollbackB64) {
            if (await this._paintCapturedScreen(initialScrollbackB64, 'rejoin') === 'painted') {
                this._needsReplayCtrlL = true;
                this._pendingPostConnectScroll = true;
            }
        } else if (session && session.initial_scrollback_pending && window.TerminalHistoryGate) {
            this._pendingPostConnectScroll = true;
            window.TerminalHistoryGate.begin(this, session.initial_scrollback_pending);
        }

        await this._connectWhenReady('scheduled reconnect');
    }

    async waitForFontsAndLayout(container) {
        if (!window.TerminalReadiness) return null;
        return window.TerminalReadiness.waitForContainer(container, this);
    }

    async connectWebSocket(opts = {}) {
        if (this._disposed || !this.term) return;
        const connectingTerm = this.term;
        if (this.isReconnecting) {
            if (opts && opts.scheduled) {
                this.isReconnecting = false;
            } else {
                this.stopReconnecting();
            }
        }

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log('Terminal: Already connected');
            return;
        }

        this._socketEverOpened = false;
        this._bytesEverSeen = false;

        if (window.TerminalSocketAbandon?.abandonIfConnecting(this.ws, WebSocket)) {
            this.ws = null;
            console.log('Terminal: closed a superseded CONNECTING socket');
        }

        this.updateStatus('Connecting to terminal...');

        const container = this._containerEl();
        await this.waitForFontsAndLayout(container);
        if (this._disposed || this.term !== connectingTerm) return;

        const measured = window.TerminalReadiness
            ? await window.TerminalReadiness.measure(this)
            : { fitted: false, reason: 'no-readiness-module', attempts: 0, waitedMs: 0 };
        if (this._disposed || this.term !== connectingTerm) return;
        console.log('Terminal size:', this.term.cols, 'x', this.term.rows,
            `measured=${measured.fitted} reason=${measured.reason} in ${measured.waitedMs}ms`);

        const sessionId = this._sessionId();
        if (window.TerminalSessionBind) window.TerminalSessionBind.announce(this, sessionId);
        const wsURL = window.API.getWebSocketURL(sessionId);
        console.log('Terminal: Connecting to WebSocket:', wsURL);

        this.ws = window.API.openWebSocket(sessionId);
        this.ws.binaryType = 'arraybuffer';
        this.setupWebSocketHandlers();
    }

    _unwrapSession(s) {
        if (!s) return {};
        return (s.session && typeof s.session === 'object') ? s.session : s;
    }

    _sessionId() {
        return this._unwrapSession(this._currentSession).id || null;
    }

    /* no evidence at all */
    _noteUserInputToSession(data) {
        const sessionId = this._sessionId();
        if (!sessionId) return;
        if (window.ToastManager
            && typeof window.ToastManager.dismissForSessionActivity === 'function') {
            window.ToastManager.dismissForSessionActivity(sessionId, data);
        }
    }

    _currentTmuxName() {
        const s = this._currentSession;
        if (!s) return null;
        if (s.tmux_session) return s.tmux_session;
        return this._unwrapSession(s).tmux_session || null;
    }

    _enterHeaderRename() {
        if (window.TerminalHeaderRename) window.TerminalHeaderRename.enter(this);
    }

    _exitHeaderRename(newName) {
        if (window.TerminalHeaderRename) window.TerminalHeaderRename.exit(newName);
    }

    setupWebSocketHandlers() {
        if (!this.ws) return;

        const sock = this.ws;
        const boundSessionId = this._sessionId();
        const live = (what) => {
            const verdict = window.TerminalFrameGuard
                ? window.TerminalFrameGuard.accepts({
                    socket: sock,
                    liveSocket: this.ws,
                    boundSessionId,
                    currentSessionId: this._sessionId(),
                })
                : { ok: sock === this.ws, reason: 'guard-unavailable' };
            if (!verdict.ok) {
                sock.onmessage = null;
                sock.onopen = null;
                sock.onerror = null;
                sock.onclose = null;
                console.warn(
                    `Terminal: dropped ${what} from ${verdict.reason}`,
                    { boundSessionId, currentSessionId: this._sessionId() }
                );
            }
            return verdict.ok;
        };

        this.ws.onopen = () => {
            if (!live('open')) return;
            console.log('Terminal: WebSocket connected');

            // client/js/terminal-reconnect-policy.js.
            this._socketEverOpened = true;
            this.isReconnecting = false;
            this._intentionalClose = false;
            this._reconnectByNameAttempted = false;
            this._authProbeAttempted = false;
            if (this.reconnectTimeout) {
                clearTimeout(this.reconnectTimeout);
                this.reconnectTimeout = null;
            }

            if (this._m('TerminalInputBuffer')) this._m('TerminalInputBuffer').armReadyBackstop(this);

            this.updateStatus('Connected', 'connected');

            const sidForToasts = this._sessionId();
            if (sidForToasts && window.API && window.ToastManager &&
                typeof window.API.getSessionToasts === 'function') {
                window.API.getSessionToasts(sidForToasts, { unackedOnly: true })
                    .then((toasts) => {
                        if (Array.isArray(toasts) && toasts.length) {
                            window.ToastManager.backfill(toasts);
                        }
                    })
                    .catch((err) => {
                        console.warn('[Toast] backfill failed', err && err.message);
                    });
            }

            if (globalThis.PreferencesTransport) globalThis.PreferencesTransport.refreshOnReconnect();

            this.sendResize('ws.onopen');

            this._needsReplayCtrlL = false;

            if (this._pendingPostConnectScroll) {
                this._pendingPostConnectScroll = false;
                this._forceScrollToBottom(800);
            }

            if (globalThis.SessionTransport) {
                globalThis.SessionTransport.mark(
                    this._currentTmuxName(),
                    globalThis.SessionTransport.CONNECTED);
            }

            if (this.keepaliveInterval) {
                clearInterval(this.keepaliveInterval);
            }
            this.keepaliveInterval = setInterval(() => {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({type: "ping"}));
                }
            }, 30000);
        };

        this.ws.onmessage = (event) => {
            if (!live('frame')) return;
            if (event.data instanceof ArrayBuffer) {
                if (!this._bytesEverSeen) this._noteInitializationSuccess();
                this.enqueue(new Uint8Array(event.data));
                return;
            }

            try {
                const message = JSON.parse(event.data);
                this.handleWebSocketMessage(message);
            } catch (error) {
                console.error('Terminal: Failed to parse message:', error);
            }
        };

        this.ws.onerror = (error) => {
            if (!live('error')) return;
            console.error('Terminal: WebSocket error:', error);
            this.updateStatus('WebSocket error', 'error');
        };

        this.ws.onclose = (event) => {
            if (!live('close')) {
                if (!this.ws && this.keepaliveInterval) {
                    clearInterval(this.keepaliveInterval);
                    this.keepaliveInterval = null;
                }
                return;
            }
            const closeCode = (event && typeof event.code === 'number') ? event.code : null;
            console.log('Terminal: WebSocket closed', { code: closeCode });
            this.ws = null;

            if (window.TerminalHistoryGate) window.TerminalHistoryGate.release(this, 'the socket closed');
            if (this._m('TerminalInputBuffer')) {
                this._m('TerminalInputBuffer').abandon(this, 'the socket closed, code ' + closeCode);
            }

            if (this.keepaliveInterval) {
                clearInterval(this.keepaliveInterval);
                this.keepaliveInterval = null;
            }

            if (this._intentionalClose) {
                console.log('Terminal: intentional close, skipping reconnect');
                this._intentionalClose = false;
                if (globalThis.SessionTransport) {
                    globalThis.SessionTransport.clear();
                }
                return;
            }

            if (globalThis.SessionTransport) {
                globalThis.SessionTransport.mark(
                    this._currentTmuxName(),
                    globalThis.SessionTransport.DISCONNECTED);
            }

            this.updateStatus('Disconnected', 'error');
            this._showStatusPill('disconnected', 'error');

            this._scheduleRecovery(closeCode);
        };
    }

    _scheduleRecovery(closeCode) {
        if (!this.sessionActive || this.isReconnecting) return;
        const policy = window.TerminalReconnectPolicy;
        const watch = window.ServerRestartWatch;
        const outageCodeKnown = !this._restartWatchActive && !!watch
            && typeof watch.isOutageCloseCode === 'function'
            && watch.isOutageCloseCode(closeCode);
        const recovery = policy
            ? policy.recoveryFor({
                code: closeCode,
                intentional: false,
                byNameAlreadyTried: !!this._reconnectByNameAttempted,
                outageCodeKnown,
                socketOpened: this._socketEverOpened,
                authProbeAlreadyTried: !!this._authProbeAttempted,
            })
            : 'retry_same_id';

        if (recovery === 'refresh_auth') {
            this._authProbeAttempted = true;
            this._handleAuthFailedClose(closeCode);
            return;
        }
        if (recovery === 're_resolve_by_name') {
            this._reconnectByNameAttempted = true;
            this._attemptReconnectByName(this._currentTmuxName());
            return;
        }
        if (recovery === 'wait_for_server') {
            this._handlePossibleOutage();
            return;
        }
        this.attemptReconnect();
    }

    handleWebSocketMessage(message) {
        const type = message.type;

        if (type === 'log') {
            if (message.content) this._showStatusPill(message.content, 'info');
        } else if (type === 'error') {
            this._showStatusPill(`error: ${message.message}`, 'error');
        } else if (type === 'pong') {
            console.log('Terminal: Received pong');
        } else if (type === 'toast.new') {
            if (window.ToastManager && message && message.toast) {
                window.ToastManager.add(message.toast);
            }
        } else if (type === 'preferences.changed') {
            if (globalThis.PreferencesTransport) globalThis.PreferencesTransport.handleFrame(message);
        } else if (type === 'toast.ack') {
            if (window.ToastManager && message && message.toast_id) {
                window.ToastManager.dismiss(message.toast_id, { syncToServer: false });
            }
        } else if (type === 'session.renamed') {
            try {
                const myId = this._sessionId();
                const sess = this._currentSession;
                if (message && message.session_id === myId && sess && message.new_name) {
                    sess.label = message.new_name;
                    if (sess.session && typeof sess.session === 'object') sess.session.label = message.new_name;
                    if (typeof window.setHeaderIdentity === 'function') {
                        window.setHeaderIdentity({
                            icon: 'cloude',
                            title: message.new_name,
                        });
                    }
                    if (typeof window.setPageTitle === 'function') {
                        window.setPageTitle(message.new_name);
                    }
                    if (typeof this._exitHeaderRename === 'function') {
                        this._exitHeaderRename(message.new_name);
                    }
                }
                if (window.Launchpad && typeof window.Launchpad.loadRunningSessions === 'function') {
                    try { window.Launchpad.loadRunningSessions(); } catch (_) {  }
                }
            } catch (err) {
                console.warn('Terminal: session.renamed handling failed:', err);
            }
        } else if (type === 'request_dims') {
            if (this.fitAddon && this.term) {
                const r = window.TerminalMetrics?.guardedFit
                    ? window.TerminalMetrics.guardedFit(this) : { fitted: false, reason: 'no-metrics' };
                if (!r.fitted) console.warn(`[TERM-RESIZE] handshake fit skipped, reason=${r.reason}`);
                this.sendResize('handshake', true );
            }
        } else if (type === 'terminal_size' || type === 'size_master') {
            if (this._m('TerminalSizeVote')) this._m('TerminalSizeVote').onTerminalSize(this, message);
        } else if (type === 'terminal.ready') {
            if (this._paintHeld && window.TerminalPaintGate) window.TerminalPaintGate.reassert(this);
            // there is nothing
            if (this._m('TerminalInputBuffer')) {
                this._m('TerminalInputBuffer').flushOnReady(this, message);
            }
        } else if (type === 'terminal.resync') {
            if (this._m('TerminalViewerResync')) this._m('TerminalViewerResync').onResync(this, message);
        }
    }

    /* gets a healthy session declared unreachable the server did not answer */
    attemptReconnect() {
        const policy = window.TerminalReconnectPolicy;
        const outcome = this._measuredInitOutcome();
        this._initOutcome = outcome;
        const charge = policy
            ? policy.consumesBudget({
                socketOpened: this._socketEverOpened, outcome })
            : true;
        if (charge) this.reconnectAttempts += 1;

        if (!this.sessionActive || this.reconnectAttempts > this.maxReconnectAttempts) {
            if (this.reconnectAttempts > this.maxReconnectAttempts
                && !this._unreachableReported) {
                this._unreachableReported = true;
                console.log('Terminal: Max reconnect attempts reached');
                this.updateStatus('Connection failed', 'error');
                this._showStatusPill(
                    `reconnection failed after ${this.maxReconnectAttempts} attempts`, 'error');
            }
            this.stopReconnecting();
            return;
        }

        this.isReconnecting = true;
        this._attemptsSinceProgress += 1;
        const delay = policy
            ? policy.backoffMs(this._attemptsSinceProgress)
            : 1000;

        console.log(`Terminal: reconnect attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts} in ${delay}ms, last outcome ${outcome}`);
        this.updateStatus('Reconnecting...');
        this._showStatusPill(
            `reconnecting, attempt ${this.reconnectAttempts} of ${this.maxReconnectAttempts}`, 'info');

        this.reconnectTimeout = setTimeout(() => {
            this.reconnectTimeout = null;
            // session nobody is looking at
            if (!this._navCurrent('scheduled reconnect attempt')) {
                this.stopReconnecting();
                return;
            }
            this.connectWebSocket({ scheduled: true });
        }, delay);
    }

    stopReconnecting() {
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }
        this.isReconnecting = false;
    }

    _resetRetryBudget(reason) {
        if (this.reconnectAttempts || this._attemptsSinceProgress) {
            console.log('Terminal: retry budget reset -', reason);
        }
        this.reconnectAttempts = 0;
        this._attemptsSinceProgress = 0;
        this._unreachableReported = false;
    }

    _noteInitializationSuccess() {
        this._bytesEverSeen = true;
        const policy = window.TerminalReconnectPolicy;
        this._initOutcome = policy
            ? policy.initOutcome({ socketOpened: true, bytesSeen: true })
            : 'ready';
        this._resetRetryBudget('initialization success');
    }

    _measuredInitOutcome() {
        const policy = window.TerminalReconnectPolicy;
        if (!policy) return this._bytesEverSeen ? 'ready' : 'unknown';
        const wrapper = this._currentSession || {};
        return policy.initOutcome({
            socketOpened: this._socketEverOpened,
            bytesSeen: this._bytesEverSeen,
            startupGate: wrapper.startup_gate || null,
        });
    }

    async _attemptReconnectByName(boundTmuxName = null) {
        const tmuxName = boundTmuxName || this._currentTmuxName();
        if (!tmuxName || !window.API || typeof window.API.listAttachableSessions !== 'function') {
            this.attemptReconnect();
            return;
        }

        this.isReconnecting = true;
        this.updateStatus('Reconnecting...');
        this._showStatusPill('connection restored, looking up session by name', 'info');

        let stillAlive = false;
        try {
            const attachable = await window.API.listAttachableSessions();
            stillAlive = Array.isArray(attachable) && attachable.some(s => s && s.name === tmuxName);
        } catch (err) {
            console.warn('Terminal: attachable lookup failed during 4404 recovery:', err);
            this.isReconnecting = false;
            this.attemptReconnect();
            return;
        }

        if (!stillAlive) {
            try {
                if (window.API && typeof window.API.listSessions === 'function') {
                    const live = await window.API.listSessions();
                    stillAlive = Array.isArray(live) && live.some((info) => {
                        const name = info && (info.tmux_session
                            || (info.session && info.session.tmux_session));
                        return name === tmuxName;
                    });
                }
            } catch (err) {
                console.warn('Terminal: list-sessions lookup failed during 4404 recovery:', err);
            }
        }

        this.isReconnecting = false;

        if (!stillAlive) {
            console.log('Terminal: 4404 recovery found no live tmux session named', tmuxName);
            this.sessionActive = false;
            this.stopReconnecting();
            this.updateStatus('Session ended', 'error');
            if (!window.TerminalPageOwner || !window.TerminalPageOwner.isPageOwner(this._role)) return;
            window.dispatchEvent(new CustomEvent('cloude:primary-session-gone', { detail: { tmuxName } }));
            return;
        }

        try {
            console.log('Terminal: re-adopting', tmuxName, 'after server restart');
            this._assertAdoptTargetUnchanged(tmuxName);
            const result = await window.API.adoptSession(tmuxName, true, this);
            const sessionWithScrollback = Object.assign(
                {}, result.session, { initial_scrollback_b64: result.initial_scrollback_b64 }
            );
            await this.reconnectToExistingSession(sessionWithScrollback);
        } catch (err) {
            console.error('Terminal: re-adopt after 4404 failed:', err);
            this.attemptReconnect();
        }
    }

    _assertAdoptTargetUnchanged(tmuxName) {
        if (!tmuxName) {
            throw new Error('Terminal: refusing to adopt without a tmux name');
        }
        const current = this._currentTmuxName();
        if (current && current !== tmuxName) {
            throw new Error(
                `Terminal: refusing to adopt "${tmuxName}" - this tab is bound to "${current}"`
            );
        }
    }

    _serverRestartWatch() {
        if (!this._restartWatch) {
            this._restartWatch = new window.ServerRestartWatch();
        }
        return this._restartWatch;
    }

    async _handlePossibleOutage() {
        const watch = this._serverRestartWatch();
        const status = window.ServerRestartWatch.STATUS;
        const result = window.ServerRestartWatch.RESULT;
        const boundTmuxName = this._currentTmuxName();
        const offlineAtClose = watch.isClientOffline();
        let outcome = null;

        this._restartWatchActive = true;
        try {
            if (!offlineAtClose && await watch.probe()) {
                console.log('Terminal: server is answering, treating close as a transient blip');
                if (this.sessionActive && !this.isReconnecting) {
                    this._restartWatchActive = false;
                    this.attemptReconnect();
                }
                return;
            }

            if (offlineAtClose) {
                console.log('Terminal: this client is offline, waiting for the network');
                this.updateStatus(status.OFFLINE);
                this._showStatusPill(
                    'no network connection on this device, waiting for it to come back', 'info');
            } else {
                console.log('Terminal: no answer from the server, waiting for it to become reachable');
                this.updateStatus(status.WAITING);
                this._showStatusPill(
                    'no answer from the server, it may be restarting or unreachable, waiting', 'info');
            }

            let showingOffline = offlineAtClose;
            outcome = await watch.waitForServer({
                shouldAbort: () => !this.sessionActive,
                onAttempt: ({ attempt, elapsedMs, clientOffline }) => {
                    if (clientOffline !== showingOffline) {
                        showingOffline = clientOffline;
                        this.updateStatus(clientOffline ? status.OFFLINE : status.WAITING);
                    }
                    if (attempt > 1 && attempt % 5 === 0) {
                        const secs = Math.round(elapsedMs / 1000);
                        this._showStatusPill(clientOffline
                            ? 'still no network connection on this device'
                            : `still no answer from the server, ${secs}s`, 'info');
                    }
                },
            });
        } finally {
            this._restartWatchActive = false;
        }

        if (outcome === result.ABORTED || !this.sessionActive) {
            console.log('Terminal: outage wait aborted, session is no longer active');
            this.stopReconnecting();
            return;
        }

        if (outcome === result.TIMEOUT) {
            console.warn('Terminal: server stayed unreachable through the watch ceiling');
            this.stopReconnecting();
            this.updateStatus(status.UNREACHABLE, 'error');
            this._showStatusPill('still cannot reach the server, reload once it is back', 'error');
            return;
        }

        console.log('Terminal: server is reachable again, re-resolving session by name');
        this.updateStatus(status.BACK);
        this._reconnectByNameAttempted = true;
        await this._attemptReconnectByName(boundTmuxName);
    }

    async _handleAuthFailedClose(closeCode) {
        if (this.isReconnecting) return;
        this.isReconnecting = true;
        this.updateStatus('Refreshing auth...');

        const recovery = window.SocketAuthRecovery;
        const outcome = recovery
            ? await recovery.resolveAfterUnopenedClose(recovery.defaultRefreshFn())
            : 'no-refresh-path';

        this.isReconnecting = false;

        if (outcome === 'refreshed') {
            console.log('Terminal: refresh ok after unopened close, reconnecting');
            this.attemptReconnect();
            return;
        }
        if (outcome === 'signed-out') {
            console.warn('Terminal: refresh failed after unopened close, escalating to re-auth');
            if (window.API && typeof window.API.handleUnauthorized === 'function') {
                window.API.handleUnauthorized();
            } else {
                window.dispatchEvent(new CustomEvent('auth-required'));
            }
            return;
        }
        console.warn('Terminal: refresh unresolved after unopened close, deferring to the ordinary ladder');
        if (this.sessionActive) this._scheduleRecovery(closeCode);
    }

    async destroySession(action = null, { confirmedBy = null } = {}) {
        const name = this._currentTmuxName() || (this._currentSession && this._currentSession.id) || 'this session';
        if (!confirmedBy) {
            if (!window.SessionRowActions) {
                console.error('Terminal: SessionRowActions missing, refusing to destroy');
                return;
            }
            const confirmed = await window.SessionRowActions.confirm(
                action || window.SessionRowActions.ACTION_CLOSE, name);
            if (!confirmed) {
                return;
            }
        }

        try {
            this.updateStatus('Destroying session...');

            const sessionId = this._sessionId();
            await window.API.destroySession(sessionId);

            if (sessionId && window.ToastManager &&
                typeof window.ToastManager.dismissBySession === 'function') {
                window.ToastManager.dismissBySession(sessionId);
            }

            this.sessionActive = false;
            this.stopReconnecting();

            if (this.ws) {
                this.ws.close();
                this.ws = null;
            }

            if (this.detachSessionBtn) this.detachSessionBtn.disabled = true;

            if (this.term) {
                this.term.clear();
                this.term.writeln('\x1b[1;31mSession destroyed\x1b[0m\n');
            }

            window.dispatchEvent(new CustomEvent('session-destroyed'));

        } catch (error) {
            console.error('Terminal: Error destroying session:', error);
            this.updateStatus('Error: ' + error.message, 'error');
        }
    }

    /* the current session */
    async detachSession() {
        try {
            this.updateStatus('Detaching session...');

            const sessionId = this._sessionId();
            await window.API.detachSession(sessionId);

            this.sessionActive = false;
            this.stopReconnecting();
            this._reconnectByNameAttempted = false;

            if (this.ws) {
                this._intentionalClose = true;
                this.ws.close();
                this.ws = null;
            }

            if (this.detachSessionBtn) this.detachSessionBtn.disabled = true;

            if (this.term) {
                this.term.clear();
                this.term.writeln('\x1b[1;33mSession detached - still running, re-adopt it from the launchpad\x1b[0m\n');
            }

            window.dispatchEvent(new CustomEvent('session-destroyed'));

        } catch (error) {
            console.error('Terminal: Error detaching session:', error);
            this.updateStatus('Error: ' + error.message, 'error');
        }
    }

    pauseForHome() {
        if (this.ws) {
            try {
                this._intentionalClose = true;
                this.ws.close();
            } catch (e) {
                console.warn('Terminal: error closing WS on Home:', e);
            }
            this.ws = null;
        }
        if (this.keepaliveInterval) {
            clearInterval(this.keepaliveInterval);
            this.keepaliveInterval = null;
        }
    }

    dispose() {
        if (window.TerminalTeardown) { window.TerminalTeardown.dispose(this); return; }
        console.error('Terminal: terminal-teardown.js missing, socket only');
        this._disposed = true;
        this.stopReconnecting();
        this.pauseForHome();
    }

    insertText(text, ticket) {
        if (window.TerminalInputOwnership
            && !window.TerminalInputOwnership.deliver(this, ticket)) return;

        if (this.term) this.term.paste(text);
        else console.warn('Terminal: text not delivered, no terminal yet');
    }

    updateStatus(text, className) {
        this.connectionStatus = { text, className: className || '' };
        window.dispatchEvent(new CustomEvent('cloude:terminal-connection', {
            detail: { controller: this, ...this.connectionStatus }
        }));
        if (this.statusEl) {
            this.statusEl.setAttribute('data-status', text);
            this.statusEl.setAttribute('aria-label', text);
            this.statusEl.className = 'status ' + className;
        }
    }
}

// THE CLASS ENDS ABOVE.
if (!window.CloudeTerminal || typeof window.CloudeTerminal.register !== 'function') {
    throw new Error(
        'Terminal: client/js/terminal-client-factory.js did not load before '
        + 'terminal.js, so there is nothing to build the terminal client with');
}
window.CloudeTerminal.register(Terminal);
window.TerminalController = window.CloudeTerminal.createTerminalClient(
    document.getElementById('terminal'), { role: { pageOwner: true } });
console.log('[Terminal Module] Exported as window.TerminalController:', window.TerminalController);
