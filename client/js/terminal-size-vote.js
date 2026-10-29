/* nobody is looking at */

console.log('[TerminalSizeVote Module] Loading...');

(function (global) {

    function isHidden(doc) {
        return !!doc && (doc.visibilityState === 'hidden' || global.CarnivoreWindowHidden === true);
    }

    function paintsNotice(ctl) {
        return !!ctl && typeof ctl._chrome === 'function' && !!ctl._chrome('statusText');
    }

    function web() {
        return global.CloudeWeb;
    }

    function clear(ctl) {
        if (ctl) {
            ctl._paneLimit = null;
            ctl._sizeMaster = undefined;
            if (ctl._repaintTimer) clearTimeout(ctl._repaintTimer);
            ctl._repaintTimer = null;
        }
        clearNotice(ctl);
    }

    function clearNotice(ctl) {
        if (!paintsNotice(ctl)) return;
        var host = web();
        if (host && typeof host.clearTerminalSizeNotice === 'function') {
            host.clearTerminalSizeNotice();
        }
    }

    function constrainedBy(message, cols, rows) {
        if (!message || !(message.clients > 1)) return false;
        if (!(cols > 0) || !(rows > 0)) return false;
        if (!(message.cols > 0) || !(message.rows > 0)) return false;
        return message.cols < cols || message.rows < rows;
    }

    function onTerminalSize(ctl, message) {
        if (message && message.type === 'size_master') {
            onSizeMaster(ctl, message);
            return;
        }
        if (setPaneLimit(ctl, message) && showGrid(ctl)) scheduleRepaint(ctl);
        if (!paintsNotice(ctl)) return;
        var host = web();
        if (!host) return;
        if (!isFollowing(ctl) && constrainedBy(message, ctl.lastSentCols, ctl.lastSentRows)) {
            if (typeof host.showTerminalSizeNotice === 'function') {
                host.showTerminalSizeNotice(message.cols, message.rows);
            }
        } else if (typeof host.clearTerminalSizeNotice === 'function') {
            host.clearTerminalSizeNotice();
        }
    }

    function onSizeMaster(ctl, message) {
        var master = global.TerminalSizeMaster;
        if (!ctl || !master) return;
        var changed = master.note(ctl, message);
        if (showGrid(ctl) || (changed && !isFrozen(ctl))) scheduleRepaint(ctl);
        if (isFollowing(ctl)) clearNotice(ctl);
    }

    function isFollowing(ctl) {
        var master = global.TerminalSizeMaster;
        return !!master && master.isFollower(ctl);
    }

    function showsPane(ctl) {
        return isFollowing(ctl) || isHidden(global.document) || isFrozen(ctl);
    }

    var REPAINT_DELAY_MS = 250;

    function voteGrid(ctl) {
        var fit = ctl && ctl._fitGrid;
        if (fit && fit.cols > 0 && fit.rows > 0) return { cols: fit.cols, rows: fit.rows };
        var t = ctl && ctl.term;
        return t ? { cols: t.cols, rows: t.rows } : null;
    }

    function shownGrid(ctl) {
        var fit = voteGrid(ctl);
        var lim = ctl && ctl._paneLimit;
        if (!fit || !lim) return fit;
        if (showsPane(ctl)) return { cols: lim.cols, rows: lim.rows };
        if (lim.lone) return fit;
        return { cols: Math.min(fit.cols, lim.cols), rows: Math.min(fit.rows, lim.rows) };
    }

    function showGrid(ctl) {
        if (isFrozen(ctl) && !(ctl && ctl._paneLimit)) return false;
        var lim = ctl && ctl._paneLimit;
        if (lim && lim.lone && !showsPane(ctl)) {
            var own = voteGrid(ctl);
            if (own) ctl._paneLimit = { cols: own.cols, rows: own.rows, lone: true };
        }
        var t = ctl && ctl.term;
        var g = shownGrid(ctl);
        if (!t || !g || typeof t.resize !== 'function') return false;
        var master = global.TerminalSizeMaster;
        if (master) master.applyScale(ctl, master.scaleFor(voteGrid(ctl), g, showsPane(ctl)));
        if (t.cols === g.cols && t.rows === g.rows) return false;
        try {
            if (global.TerminalProvider) global.TerminalProvider.wrap(t).clearRenderer();
            t.resize(g.cols, g.rows);
        } catch (err) {
            console.warn('[TERM-RESIZE] pane grid not applied', err);
            return false;
        }
        return true;
    }

    function setPaneLimit(ctl, message) {
        if (!ctl || !message || !(message.cols > 0) || !(message.rows > 0)) return false;
        ctl._paneLimit = { cols: message.cols, rows: message.rows, lone: message.clients === 1 };
        return true;
    }

    function fitTo(ctl, proposal) {
        if (!ctl || !proposal) return;
        ctl._fitGrid = { cols: proposal.cols, rows: proposal.rows };
        showGrid(ctl);
    }

    function scheduleRepaint(ctl) {
        var ws = ctl.ws;
        if (!ws || typeof ws.send !== 'function') return;
        if (ctl._repaintTimer) clearTimeout(ctl._repaintTimer);
        ctl._repaintTimer = setTimeout(function () {
            ctl._repaintTimer = null;
            if (ctl.ws !== ws || ws.readyState !== 1) return;
            try {
                ws.send(JSON.stringify({ type: 'repaint' }));
            } catch (err) {
                console.warn('[TERM-RESIZE] repaint request not sent', err);
            }
        }, REPAINT_DELAY_MS);
    }

    /* nobody is looking at */
    function isWithdrawn(ctl, doc) {
        return isHidden(doc) || !!(ctl && ctl._tabHidden);
    }

    function isFrozen(ctl) {
        return !!(ctl && ctl._tabHidden);
    }

    function rejoin(ctl, reason) {
        var t = ctl.term;
        var before = t ? t.cols + 'x' + t.rows : '';
        var metrics = global.TerminalMetrics;
        if (metrics && typeof metrics.guardedFit === 'function') {
            var fit = metrics.guardedFit(ctl);
            if (fit && fit.fitted && typeof metrics.enforceWidthFit === 'function') {
                metrics.enforceWidthFit(ctl);
            }
        }
        showGrid(ctl);
        clearNotice(ctl);
        ctl.sendResize(reason, true);
        var moved = !!t && before !== t.cols + 'x' + t.rows;
        if (ctl._thawRepaint || moved) {
            ctl._thawRepaint = false;
            scheduleRepaint(ctl);
        }
    }

    function adoptGrid(ctl, doc) {
        if (isHidden(doc) || isFrozen(ctl)) return {};
        if (ctl) {
            var own = voteGrid(ctl);
            return own ? { cols: own.cols, rows: own.rows } : {};
        }
        var metrics = global.TerminalMetrics;
        return metrics && typeof metrics.currentGrid === 'function' ? metrics.currentGrid() : {};
    }

    function canSend(ctl) {
        return !!ctl && !!ctl.term && typeof ctl.sendResize === 'function';
    }

    function onVisibilityChange(ctl, doc) {
        if (!canSend(ctl)) return;
        if (isHidden(doc)) {
            ctl.sendResize('visibility.hidden', true);
            return;
        }
        if (ctl._tabHidden) return;
        rejoin(ctl, 'visibility.visible');
    }

    function setTabHidden(ctl, hidden, doc) {
        if (!ctl) return;
        var next = !!hidden;
        if (!!ctl._tabHidden === next) return;
        ctl._tabHidden = next;
        if (next) ctl._thawRepaint = true;
        if (!canSend(ctl) || isHidden(doc)) return;
        if (next) ctl.sendResize('tab.hidden', true);
        else rejoin(ctl, 'tab.visible');
    }

    global.TerminalSizeVote = {
        isHidden: isHidden,
        isWithdrawn: isWithdrawn,
        isFrozen: isFrozen,
        isFollowing: isFollowing,
        showsPane: showsPane,
        adoptGrid: adoptGrid,
        setTabHidden: setTabHidden,
        constrainedBy: constrainedBy,
        voteGrid: voteGrid,
        fitTo: fitTo,
        onTerminalSize: onTerminalSize,
        onVisibilityChange: onVisibilityChange,
        clear: clear
    };
}(typeof window !== 'undefined' ? window : globalThis));
