
console.log('[SessionRestartPicker Module] Loading...');

(function () {
    'use strict';

    var Options = window.SessionRestartOptions;

    var overlayEl = null;

    var releaseTrap = function () {};

    var choiceHandle = null;

    var pendingResolve = null;

    function esc(value) {
        return Options.esc(value);
    }

    function tr(key, params) {
        return Options.tr(key, params);
    }

    function rowEnabled(data, live) {
        data = data || {};
        return data['actionable-now'] === '1'
            || (live === true && data['live-eligible'] === '1');
    }

    /* could not be read */
    function noticeHtml(preview) {
        var out = preview.pane_state === 'unknown'
            ? '<div class="restart-picker__notice">'
                + esc(tr('session.restart.picker.pane_unknown')) + '</div>'
            : '';
        return out + wrapperNoticeHtml(preview);
    }

    function wrapperNoticeHtml(preview) {
        var key = preview.wrappers_status === 'unavailable'
            ? 'session.restart.picker.wrappers_unreadable'
            : (!(preview.options || []).length
                ? 'session.restart.picker.no_wrappers' : '');
        return key
            ? '<div class="restart-picker__notice">' + esc(tr(key)) + '</div>'
            : '';
    }

    function stateHtml(preview, status) {
        var key = window.SessionStatusUI
            ? window.SessionStatusUI.normalizeStatus(status)
            : 'unknown';
        var busy = key === 'working' || key === 'question' || key === 'notice';
        var alive = preview.pane_state === 'alive';
        var shared = Options.sharedDetail(preview).detail ? ''
            : Options.kindTag(Options.commonKind(preview) || 'agent');
        var parts = [];
        if (busy) {
            parts.push('<span class="restart-picker__state" data-state="busy">'
                + esc(key) + '</span>');
        } else if (alive) {
            parts.push('<span class="restart-picker__state" data-state="alive">'
                + esc(tr('session.restart.picker.running')) + '</span>');
        }
        if (shared) {
            parts.push('<span class="restart-picker__state" data-state="kind">'
                + esc(shared) + '</span>');
        }
        return parts.join('');
    }

    function dismiss(resolve, value) {
        pendingResolve = null;
        if (overlayEl && overlayEl.parentNode) {
            overlayEl.parentNode.removeChild(overlayEl);
        }
        overlayEl = null;
        if (choiceHandle) choiceHandle.destroy();
        choiceHandle = null;
        releaseTrap();
        releaseTrap = function () {};
        resolve(value);
    }

    function present(displayName, preview, status, mode, sessionUuid, focusWrapper, armedByGesture, busyWork, accounts) {
        mode = mode || 'restart';
        sessionUuid = sessionUuid || null;
        if (overlayEl && pendingResolve) dismiss(pendingResolve, null);
        return new Promise(function (resolve) {
            pendingResolve = resolve;
            var overlay = document.createElement('div');
            overlay.className = 'modal-overlay restart-picker';
            overlay.innerHTML =
                '<div class="modal-content restart-picker__content" '
                + 'id="restart-picker-dialog" role="dialog" '
                + 'aria-modal="true" aria-label="'
                + esc(tr('session.restart.picker.aria', { name: displayName }))
                + '">'
                + '<div class="modal-titlerow restart-picker__head">'
                + '<span class="restart-picker__verb">'
                + esc(tr('session.restart.picker.title')) + '</span>'
                + '<span class="restart-picker__name">' + esc(displayName)
                + '</span>'
                + stateHtml(preview, status)
                + '</div>'
                + '<div class="modal-body restart-picker__main">'
                + noticeHtml(preview)
                + (busyWork === true && preview.pane_state === 'alive'
                    ? '<div class="restart-picker__notice" id="restart-picker-busy">'
                        + esc(tr('session.restart.picker.busy_work')) + '</div>'
                    : '')
                + Options.sharedDetailHtml(preview)
                + '<div class="restart-picker__choice" id="restart-picker-options"></div>'
                + '<div class="restart-picker__why" id="restart-picker-why" '
                + 'aria-live="polite"></div>'
                + '</div>'
                + '<div class="modal-footer restart-picker__foot">'
                // live pane.
                + (preview.pane_state === 'alive' && window.SessionRestartLive
                    ? window.SessionRestartLive.armHtml(
                        armedByGesture === true ? { armedByGesture: true } : undefined)
                    : '')
                + '<button type="button" class="modal-btn modal-btn-secondary" '
                + 'id="restart-picker-cancel">'
                + esc(tr('session.restart.picker.cancel')) + '</button>'
                + '<button type="button" class="modal-btn modal-btn-primary" '
                + 'id="restart-picker-go">'
                + esc(tr('session.restart.picker.go')) + '</button>'
                + '</div></div>';

            document.body.appendChild(overlay);
            overlayEl = overlay;
            var choice = Options.mountChoice('restart-picker-options', preview, accounts);
            choiceHandle = choice;
            if (!choice) {
                console.error('SessionRestartPicker: the compiled launch choice is not loaded');
            }

            var go = overlay.querySelector('#restart-picker-go');
            var why = overlay.querySelector('#restart-picker-why');
            // there is nothing
            var arm = overlay.querySelector('#restart-picker-live');
            // list, so the
            var allGone = Options.sharedDetail(preview).kind
                === 'transcript_missing';

            function armed() {
                return !!(arm && arm.checked);
            }

            function sync() {
                var live = armed();
                if (choice) choice.setEnabled(function (data) { return rowEnabled(data, live); });
                var picked = choice ? choice.selected() : null;
                var ok = !!picked && !picked.disabled;
                go.disabled = !ok;
                go.classList.toggle('modal-btn-danger', live);
                go.classList.toggle('modal-btn-primary', !live);
                go.textContent = tr(live
                    ? 'session.restart.picker.go.live'
                    : 'session.restart.picker.go');
                var nowKind = picked ? (picked.data['now-kind'] || '') : '';
                var projected = picked ? (picked.data.kind || '') : '';
                var reason = '';
                if (!picked) {
                    reason = 'session.restart.picker.why.pick';
                } else if (!ok && nowKind !== 'not_dead') {
                    var lockedByArmOnly = !!arm && !live && !!picked
                        && picked.data['live-eligible'] === '1';
                    if (nowKind === 'transcript_missing'
                        || projected === 'transcript_missing') {
                        reason = allGone ? '' : 'session.restart.picker.why.missing';
                    } else if (!lockedByArmOnly) {
                        reason = 'session.restart.picker.why.unknown';
                    }
                }
                why.textContent = reason ? tr(reason) : '';
            }

            if (focusWrapper && choice) {
                choice.selectFirst(function (r) { return r.id !== 'restart-choice-keep'; });
            }

            overlay.addEventListener('change', sync);
            sync();

            releaseTrap = window.ModalStack && typeof window.ModalStack.trap === 'function'
                ? window.ModalStack.trap(overlay, {
                    onEscape: function () { dismiss(resolve, null); },
                })
                : function () {};
            overlay.addEventListener('click', function (e) {
                if (e.target === overlay) dismiss(resolve, null);
            });
            overlay.querySelector('#restart-picker-cancel')
                .addEventListener('click', function () {
                    dismiss(resolve, null);
                });
            go.addEventListener('click', function () {
                if (go.disabled) return;
                var picked = choice ? choice.selected() : null;
                var value = picked ? picked.value : '';
                dismiss(resolve, {
                    agentType: value || null,
                    confirmRestartLive: armed(),
                    mode: mode,
                    sessionUuid: sessionUuid,
                    account: choice ? choice.account() : null,
                });
            });

            var dialog = overlay.querySelector('#restart-picker-dialog');
            dialog.addEventListener('keydown', function (e) {
                if (e.key !== 'Enter' || e.isComposing) return;
                var t = e.target;
                if (!t || t.tagName !== 'INPUT') return;
                e.preventDefault();
                go.click();
            });

            var first = choice ? choice.selected() : null;
            if (first && !first.disabled && choice) choice.focus();
            else if (arm && typeof arm.focus === 'function') arm.focus();
        });
    }

    var lastErrorText = '';

    function open(tmuxName, displayName, status, sessionUuid, focusWrapper, armedByGesture, busyWork) {
        lastErrorText = '';
        return Promise.all([
            Options.previewFor(tmuxName, sessionUuid || null),
            Options.accountsFor(sessionUuid || null),
        ]).then(function (both) {
                var answer = both[0];
                return present(
                    displayName || tmuxName, answer.preview, status,
                    answer.mode, answer.sessionUuid, focusWrapper,
                    armedByGesture, busyWork, both[1]);
            }).catch(function (err) {
                lastErrorText = (err && err.message) || String(err);
                console.error('SessionRestartPicker: preview failed:', err);
                return null;
            });
    }

    function lastError() {
        return lastErrorText;
    }

    window.SessionRestartPicker = {
        KIND_TAG: Options.KIND_TAG,
        isActionable: Options.isActionable,
        optionRows: Options.optionRows,
        sharedDetail: Options.sharedDetail,
        sharedDetailHtml: Options.sharedDetailHtml,
        rowEnabled: rowEnabled,
        noticeHtml: noticeHtml,
        wrapperNoticeHtml: wrapperNoticeHtml,
        stateHtml: stateHtml,
        present: present,
        open: open,
        lastError: lastError,
    };
})();

console.log('[SessionRestartPicker Module] Exported as window.SessionRestartPicker');
