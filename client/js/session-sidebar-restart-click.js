
console.log('[SessionSidebarRestartClick Module] Loading...');

(function () {
    /* could not */
    async function runRestart(ctrl, name, rowEl, hostKey, focusWrapper, armedByGesture, busyWork, direct) {
        const picker = window.SessionRestartPicker;
        if (!picker) {
            alert(`could not restart "${name}": the restart picker did not load.`);
            return;
        }
        const trigger = (rowEl && typeof rowEl.querySelector === 'function'
            && rowEl.querySelector('[data-row-menu]'))
            || document.querySelector(`[data-row-menu="${CSS.escape(name)}"]`);
        const status = trigger
            ? trigger.getAttribute('data-row-menu-status')
            : null;
        if (!hostKey && trigger && rowEl && rowEl.contains(trigger)) {
            hostKey = trigger.getAttribute('data-row-menu-host-key') || 'local';
        }
        const nameEl = rowEl
            ? rowEl.querySelector('.session-sidebar-row-name')
            : null;
        const label = (nameEl && nameEl.textContent.trim()) || name;
        const opts = window.SessionRestartOptions;
        const records = (window.Launchpad && window.Launchpad.sessionRecords)
            || null;
        const remote = !!hostKey && hostKey !== 'local';
        const target = window.SessionKey ? window.SessionKey.forName(name, hostKey)
            : (remote ? null : name);
        if (!target) {
            alert(`could not restart "${name}": the session key module did not load.`);
            return;
        }
        const uuid = !remote && opts && opts.recreateTarget
            ? opts.recreateTarget(records, name)
            : null;
        const oneClick = direct === true ? window.SessionRestartDirect : null;
        const choice = oneClick
            ? await oneClick.open(target, label, status, uuid, busyWork === true)
            : await picker.open(
                target, label, status, uuid, !!focusWrapper,
                armedByGesture === true, busyWork === true);
        if (!choice) {
            const why = (oneClick || picker).lastError();
            if (why) {
                alert(
                    `could not work out what restarting "${name}" would do, so `
                    + `nothing was started: ${why}`
                );
            }
            return;
        }

        const recreating = choice.mode === 'recreate';
        const verb = recreating ? 'recreate' : 'restart';

        let result = null;
        try {
            result = recreating
                ? await window.API.recreateSession(
                    choice.sessionUuid, choice.agentType, choice.account)
                : await window.API.respawnSession(
                    target, choice.agentType, choice.confirmRestartLive === true,
                    choice.account);
        } catch (err) {
            console.error(`SessionSidebar: ${verb} failed:`, err);
            alert(`could not ${verb} "${name}": ${err.message || err}`);
            ctrl._lastSig = null;
            await ctrl._fetchAndRender();
            return;
        }

        const worked = recreating
            ? (result && result.status === 'started')
            : (result && result.ok === true);
        if (!worked) {
            alert(
                `could not ${verb} "${name}": `
                + ((result && result.detail) || 'no reason given')
            );
            ctrl._lastSig = null;
            await ctrl._fetchAndRender();
            return;
        }

        if (recreating) {
            result = {
                name: result.tmux_session || name,
                session_id: result.session_id || null,
                detail: result.detail || '',
            };
        }

        if (!recreating && choice.agentType
            && result.agent_type_persisted === false) {
            alert(
                `restarted "${name}" with ${choice.agentType}, but the choice `
                + 'could not be saved, so the next restart will not remember it.'
            );
        }

        const back = window.SessionRestartReturn
            ? await window.SessionRestartReturn.reopen(result)
            : { status: 'not_reopened', detail: 'the reopen module did not load' };
        if (back.status === 'reopened') {
            ctrl._closeAfterSwitch();
            return;
        }
        if (back.detail) alert(back.detail);
        ctrl._lastSig = null;
        await ctrl._fetchAndRender();
    }

    window.SessionSidebarRestartClick = { runRestart };
    console.log('[SessionSidebarRestartClick Module] Exported as window.SessionSidebarRestartClick');
})();
