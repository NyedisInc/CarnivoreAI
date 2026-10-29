
console.log('[TerminalMetrics Module] Loading...');

(function () {
    'use strict';

    const MIN_COLS = 8;
    /** @type {number} */
    const MIN_ROWS = 4;

    const MAX_COLS = 1000;
    /** @type {number} */
    const MAX_ROWS = 400;

    const FONT_TIMEOUT_MS = 3000;

    async function waitForFonts(timeoutMs = FONT_TIMEOUT_MS) {
        if (!document.fonts || !document.fonts.ready) return false;
        let timer = null;
        const timeout = new Promise((resolve) => {
            timer = setTimeout(() => resolve(false), timeoutMs);
        });
        try {
            const settled = await Promise.race([
                document.fonts.ready.then(() => true),
                timeout,
            ]);
            return settled === true;
        } catch (err) {
            console.warn('TerminalMetrics: font wait failed', err);
            return false;
        } finally {
            if (timer) clearTimeout(timer);
        }
    }

    function xtermStylesheetApplied(root) {
        const scope = root || document;
        let el = null;
        try {
            el = scope.querySelector('.xterm');
        } catch (err) {
            return true;
        }
        if (!el || typeof window.getComputedStyle !== 'function') return true;
        try {
            return window.getComputedStyle(el).position !== 'static';
        } catch (err) {
            return true;
        }
    }

    /* could not measure */
    function proposalIsSane(proposal) {
        if (!proposal) return { ok: false, reason: 'no-proposal' };
        const { cols, rows } = proposal;
        if (!Number.isFinite(cols) || !Number.isFinite(rows)) {
            return { ok: false, reason: 'non-finite' };
        }
        if (cols < MIN_COLS || rows < MIN_ROWS) {
            return { ok: false, reason: 'too-small' };
        }
        if (cols > MAX_COLS || rows > MAX_ROWS) {
            return { ok: false, reason: 'too-large' };
        }
        return { ok: true, reason: 'ok' };
    }

    function guardedFit(controller) {
        if (!controller || !controller.fitAddon || !controller.term) {
            return { fitted: false, reason: 'no-controller' };
        }
        const frozen = window.TerminalSizeVote;
        if (frozen && typeof frozen.isFrozen === 'function' && frozen.isFrozen(controller)) {
            return { fitted: false, reason: 'withdrawn' };
        }
        if (!xtermStylesheetApplied()) {
            return { fitted: false, reason: 'xterm-css-not-applied' };
        }
        let proposal = null;
        try {
            proposal = typeof controller.fitAddon.proposeDimensions === 'function'
                ? controller.fitAddon.proposeDimensions()
                : null;
        } catch (err) {
            return { fitted: false, reason: 'propose-threw' };
        }
        if (proposal === null) {
            try {
                controller.fitAddon.fit();
                const vote = window.TerminalSizeVote;
                if (vote && typeof vote.fitTo === 'function') {
                    vote.fitTo(controller, { cols: controller.term.cols, rows: controller.term.rows });
                }
                return { fitted: true, reason: 'unvalidated' };
            } catch (err) {
                return { fitted: false, reason: 'fit-threw' };
            }
        }
        const verdict = proposalIsSane(proposal);
        if (!verdict.ok) return { fitted: false, reason: verdict.reason };
        try {
            const vote = window.TerminalSizeVote;
            if (vote && typeof vote.fitTo === 'function') vote.fitTo(controller, proposal);
            else controller.fitAddon.fit();
        } catch (err) {
            return { fitted: false, reason: 'fit-threw' };
        }
        return { fitted: true, reason: 'ok' };
    }

    const WIDTH_EPSILON_PX = 1;

    function availableWidth(controller) {
        try {
            const el = controller.term.element;
            if (!el || !el.parentElement) return null;
            const parent = window.getComputedStyle(el.parentElement);
            const own = window.getComputedStyle(el);
            const outer = Math.max(0, parseInt(parent.getPropertyValue('width'), 10));
            const pad = parseInt(own.getPropertyValue('padding-left'), 10)
                + parseInt(own.getPropertyValue('padding-right'), 10);
            const scrollbar = controller.term.options.scrollback === 0
                ? 0
                : globalThis.TerminalProvider.wrap(controller.term).scrollBarWidth();
            const width = outer - pad - scrollbar;
            return Number.isFinite(width) ? width : null;
        } catch (err) {
            return null;
        }
    }

    function renderedWidth(controller) {
        try {
            const cell = globalThis.TerminalProvider.wrap(controller.term).cellSize().width;
            if (!Number.isFinite(cell) || cell <= 0) return null;
            return cell * controller.term.cols;
        } catch (err) {
            return null;
        }
    }

    function enforceWidthFit(controller) {
        const out = { changed: false, cols: null, painted: null, available: null,
            reason: 'ok' };
        if (!controller || !controller.term) {
            out.reason = 'no-controller';
            return out;
        }
        const vote = window.TerminalSizeVote;
        if (vote && typeof vote.showsPane === 'function' && vote.showsPane(controller)) {
            out.reason = 'following';
            return out;
        }
        const available = availableWidth(controller);
        let painted = renderedWidth(controller);
        if (available === null || painted === null) {
            out.reason = 'unmeasurable';
            return out;
        }
        out.available = available;
        out.cols = controller.term.cols;
        out.painted = painted;
        if (painted <= available + WIDTH_EPSILON_PX) return out;

        const cell = painted / controller.term.cols;
        const fitted = Math.max(MIN_COLS, Math.floor(available / cell));
        if (fitted >= controller.term.cols) {
            out.reason = 'overflow-unfixable';
            return out;
        }
        const box = controller._fitGrid;
        try {
            controller.term.resize(fitted, controller.term.rows);
        } catch (err) {
            out.reason = 'resize-threw';
            return out;
        }
        if (box && box.cols === out.cols) controller._fitGrid = { cols: fitted, rows: box.rows };
        painted = renderedWidth(controller);
        out.changed = true;
        out.cols = controller.term.cols;
        out.painted = painted === null ? out.painted : painted;
        out.reason = 'shrunk';
        return out;
    }

    function currentGrid() {
        try {
            const ctl = window.TerminalController;
            const t = ctl && ctl.term;
            if (!t || typeof t.cols !== 'number' || typeof t.rows !== 'number') {
                return {};
            }
            if (t.cols <= 0 || t.rows <= 0) return {};
            const fitted = guardedFit(ctl);
            if (!fitted.fitted) {
                console.warn('TerminalMetrics: pre-read fit skipped, reason='
                    + fitted.reason);
            }
            return { cols: t.cols, rows: t.rows };
        } catch (err) {
            console.warn('TerminalMetrics: currentGrid failed', err);
            return {};
        }
    }

    function describeCellMetrics(controller) {
        try {
            const term = controller && controller.term;
            if (!term) return 'cell=no-term';
            const o = term.options || {};
            let cell = 'unreadable';
            try {
                const c = globalThis.TerminalProvider.wrap(term).cellSize();
                cell = `${round2(c.width)}x${round2(c.height)}`;
            } catch (err) {
                cell = 'unreadable';
            }
            const fonts = (typeof document !== 'undefined' && document.fonts
                && document.fonts.status) || 'unknown';
            const renderer = controller._webglAddon ? 'webgl' : 'dom';
            const family = String(o.fontFamily || '').split(',')[0].trim();
            return `font=${o.fontSize} lh=${o.lineHeight} cell=${cell} `
                + `renderer=${renderer} fonts=${fonts} family=${family} `
                + describeBoxHeights();
        } catch (err) {
            return 'cell=unreadable';
        }
    }

    /* the cell changed */
    function describeBoxHeights() {
        try {
            if (typeof document === 'undefined') return 'boxes=unreadable';
            const h = (sel) => {
                const el = sel.charAt(0) === '#'
                    ? document.getElementById(sel.slice(1))
                    : document.querySelector(sel);
                return el && Number.isFinite(el.clientHeight) ? el.clientHeight : '?';
            };
            return `screen=${h('#terminal-screen')} container=${h('.terminal-container')} `
                + `term=${h('#terminal')}`;
        } catch (err) {
            return 'boxes=unreadable';
        }
    }

    function round2(n) {
        return Number.isFinite(n) ? String(Math.round(n * 100) / 100) : '?';
    }

    window.TerminalMetrics = {
        describeCellMetrics,
        describeBoxHeights,
        currentGrid,
        waitForFonts,
        xtermStylesheetApplied,
        proposalIsSane,
        guardedFit,
        availableWidth,
        renderedWidth,
        enforceWidthFit,
        WIDTH_EPSILON_PX,
        MIN_COLS,
        MIN_ROWS,
        MAX_COLS,
        MAX_ROWS,
        FONT_TIMEOUT_MS,
    };
    console.log('[TerminalMetrics Module] Exported as window.TerminalMetrics');
})();
