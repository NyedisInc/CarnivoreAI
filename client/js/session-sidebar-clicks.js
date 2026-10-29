
console.log('[SessionSidebarClicks Module] Loading...');

(function () {
    async function onRowClick(ctrl, e) {
        // the bottom bar
        if (window.SessionSidebarChromeClicks
            && window.SessionSidebarChromeClicks.claim(ctrl, e)) return;

        const shell = window.CloudeWeb && window.CloudeWeb.sidebarShell;
        if (shell && typeof shell.owns === 'function' && shell.owns(e.target)) return;

        if (window.SessionSidebarReorder && window.SessionSidebarReorder.tookClick()) return;

        if (window.SessionSidebarRename && window.SessionSidebarRename.onListClick(e)) return;
        if (window.SessionSidebarReorder && window.SessionSidebarReorder.onPinClick(e)) return;

        const keepAwakeEl = e.target.closest && e.target.closest('[data-keep-awake-session]');
        if (keepAwakeEl) {
            e.stopPropagation();
            if (window.SessionSidebarKeepAwake) {
                await window.SessionSidebarKeepAwake.onClick(ctrl, keepAwakeEl);
            }
            return;
        }

        const shareEl = e.target.closest && e.target.closest('[data-share-session-id]');
        if (shareEl) {
            e.stopPropagation();
            const dispatch = window.SessionSidebarPluginClicks;
            if (dispatch) await dispatch.onShareMarkClick(ctrl, shareEl);
            else console.error('SessionSidebar: the plugin dispatch module is not loaded');
            return;
        }

        const subagentsEl = e.target.closest && e.target.closest('[data-subagents-session-id]');
        if (subagentsEl) {
            e.stopPropagation();
            if (window.SessionSidebarSubagents) window.SessionSidebarSubagents.onClick(subagentsEl);
            else console.error('SessionSidebar: the subagents module is not loaded');
            return;
        }

        const timersEl = e.target.closest && e.target.closest('[data-timers-session-id]');
        if (timersEl) {
            e.stopPropagation();
            if (window.SessionSidebarTimers) window.SessionSidebarTimers.onClick(timersEl);
            else console.error('SessionSidebar: the timers module is not loaded');
            return;
        }

        const browserKey = e.target.closest('[data-browser-row-action]');
        if (browserKey && window.SessionSidebarBrowsers) {
            e.stopPropagation();
            await window.SessionSidebarBrowsers.onKeyClick(browserKey);
            return;
        }

        const actionEl = window.SessionRowActions
            ? e.target.closest(`[${window.SessionRowActions.ATTR_ACTION}]`)
            : null;
        if (actionEl) {
            e.stopPropagation();
            await onRowActionClick(ctrl, actionEl);
            return;
        }

        const rowEl = e.target.closest('.session-sidebar-row');
        if (!rowEl) return;

        await activateRow(ctrl, rowEl);
    }

    async function activateRow(ctrl, rowEl) {
        const name = rowEl && rowEl.dataset.name;
        if (!name) return;
        if (rowEl.dataset.asleep === '1') return;
        if (window.SessionSidebarBrowsers?.activate(ctrl, name)) return;
        if (window.SessionSidebarLayouts?.activate(ctrl, name)) return;
        if (ctrl._pendingSelection?.name === name
            && (!window.NavigationGeneration
                || window.NavigationGeneration.isCurrent(ctrl._pendingSelection.nav))) return;
        if (name === ctrl._activeTmuxName && !ctrl._pendingSelection && !(window.App && window.App.currentScreen === 'launchpad')) {
            ctrl._closeAfterSwitch();
            return;
        }
        const sessionId = rowEl.dataset.sessionId || null;
        if (sessionId && window.SoloWindow && await window.SoloWindow.focusIfOpen(sessionId)) return;
        const nav = window.NavigationGeneration
            ? window.NavigationGeneration.begin('session:' + name) : null;
        const stillOurs = () => !window.NavigationGeneration
            || window.NavigationGeneration.keep(nav, 'sidebar switch to ' + name);
        ctrl._pendingSelection = { name, nav };
        paintSelection(ctrl);
        try {
            if (sessionId) {
                const info = await window.API.getSession(sessionId, { includeScrollback: true, parallelHistory: true, scrollbackLines: window.CloudeTerminal.SCROLLBACK_ROWS });
                if (!stillOurs()) return;
                if (info) {
                    ctrl._closeAfterSwitch();
                    await window.App.returnToExistingTerminal(info);
                }
                return;
            }
            const response = await window.API.adoptSession(name, true);
            if (!stillOurs()) return;
            const session = response.session || response;
            ctrl._closeAfterSwitch();
            window.dispatchEvent(new CustomEvent('session-created', {
                detail: {
                    session,
                    initialScrollbackB64: response.initial_scrollback_b64 || '',
                    fifoStartOffset: typeof response.fifo_start_offset === 'number'
                        ? response.fifo_start_offset
                        : null,
                    adopted: true,
                },
            }));
        } catch (err) {
            if (!stillOurs()) return;
            console.error('SessionSidebar: switch failed:', err);
            alert(`error: failed to switch agent: ${err.message || err}`);
        } finally {
            if (ctrl._pendingSelection?.nav === nav) {
                ctrl._pendingSelection = null;
                paintSelection(ctrl);
            }
        }
    }

    function paintSelection(ctrl) {
        const shell = window.CloudeWeb && window.CloudeWeb.sidebarShell;
        if (shell && typeof shell.drew === 'function' && shell.drew(ctrl && ctrl.listEl)) {
            shell.paintSelection(ctrl);
            return;
        }
        const pending = ctrl._pendingSelection;
        const current = pending && (!window.NavigationGeneration
            || window.NavigationGeneration.isCurrent(pending.nav));
        let name;
        if (current) {
            name = pending.name;
        } else {
            const LP = window.CloudeWeb && window.CloudeWeb.layoutPage;
            const openLayout = (LP && typeof LP.isActive === 'function' && LP.isActive()
                && typeof LP.current === 'function') ? LP.current() : null;
            const browser = window.CloudeWeb && window.CloudeWeb.browsers
                && typeof window.CloudeWeb.browsers.showing === 'function'
                ? window.CloudeWeb.browsers.showing() : null;
            name = openLayout ? `layout:${openLayout.uuid}`
                : (browser ? `browser:${browser}` : ctrl._activeTmuxName);
        }
        for (const row of ctrl.listEl?.querySelectorAll('.session-sidebar-row') || []) {
            row.setAttribute('aria-selected', row.dataset.name === name ? 'true' : 'false');
        }
    }

    async function onRowActionClick(ctrl, btnEl) {
        const actions = window.SessionRowActions;
        const name = btnEl.getAttribute(actions.ATTR_NAME);
        if (!name) return;
        const action = btnEl.getAttribute(actions.ATTR_ACTION) || actions.ACTION_CLOSE;
        const rowEl = btnEl.closest('.session-sidebar-row')
            || document.querySelector(
                `.session-sidebar-row[data-name="${CSS.escape(name)}"]`);
        const isThisTab = !!rowEl && rowEl.dataset.active === '1';

        // could not
        if (action === actions.ACTION_RESTART) {
            await window.SessionSidebarRestartClick.runRestart(ctrl, name, rowEl);
            return;
        }

        if (isThisTab) {
            ctrl._closeAfterSwitch();
            await window.TerminalController.destroySession(action);
            return;
        }

        const confirmed = await actions.confirm(action, name);
        if (!confirmed) return;

        try {
            const sessionId = rowEl ? (rowEl.dataset.sessionId || null) : null;
            if (sessionId) {
                await window.API.destroySession(sessionId);
            } else {
                await window.API.destroyExternalSession(name);
            }
            ctrl._lastSig = null;
            await ctrl._fetchAndRender();
        } catch (err) {
            console.error(`SessionSidebar: ${action} failed:`, err);
            alert(`error: failed to ${action} agent: ${err.message || err}`);
        }
    }

    window.SessionSidebarClicks = {
        onRowClick, activateRow,
        paintSelection, onRowActionClick,
        runRestart: window.SessionSidebarRestartClick.runRestart,
    };
    console.log('[SessionSidebarClicks Module] Exported as window.SessionSidebarClicks');
})();
