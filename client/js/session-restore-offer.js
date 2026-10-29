(function () {
    'use strict';

    var FIRST_CHECK_DELAY_MS = 1500;
    var RECHECK_INTERVAL_MS = 60000;
    var ENDPOINT = '/sessions/restore-offer';
    var GATE_AWAITING = 'awaiting_startup_prompt';

    var BLOCK_WORDS = {
        already_running_elsewhere: 'already running elsewhere',
        unidentified_claude_here: 'a claude in this folder could not be identified',
        writers_unmeasured: 'running sessions could not be checked',
        no_conversation: 'no conversation recorded',
        transcript_missing: 'the conversation file is missing',
        name_in_use: 'another session is using its name',
        no_wrapper: 'no wrapper to start it with',
        presence_unmeasured: 'could not check whether it is running',
        row_missing: 'its record could not be read',
    };

    var TRUST_NOTE = 'claude will ask to trust this folder';

    var PROGRESS_FRAME = 'restore_offer.progress';
    var PROGRESS_KEYS = {
        queued: 'restore_offer.row.queued',
        restoring: 'restore_offer.row.restoring',
        opened: 'restore_offer.row.opened',
        failed: 'restore_offer.row.failed',
        header: 'restore_offer.progress.header',
        checking: 'restore_offer.progress.checking',
    };

    var started = false;
    var overlayEl = null;
    var shownIds = {};

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function plural(n, one, many) {
        return n === 1 ? one : many;
    }

    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    function progressStart(chosen) {
        var state = { order: [], rows: {} };
        chosen.forEach(function (c) {
            state.order.push(c.session_uuid);
            state.rows[c.session_uuid] = { phase: 'queued', detail: '' };
        });
        return state;
    }

    function applyProgress(state, offerId, frame) {
        if (!frame || frame.type !== PROGRESS_FRAME || frame.offer_id !== offerId) return false;
        var row = state.rows[frame.session_uuid];
        if (!row || row.phase === 'opened' || row.phase === 'failed') return false;
        if (frame.phase === 'restoring') {
            if (row.phase !== 'queued') return false;
            row.phase = 'restoring';
            return true;
        }
        if (frame.phase === 'done') {
            row.phase = frame.outcome === 'reopened' ? 'opened' : 'failed';
            row.detail = frame.detail || '';
            return true;
        }
        return false;
    }

    function progressHeader(state) {
        var total = state.order.length;
        var settled = state.order.filter(function (id) {
            var p = state.rows[id].phase;
            return p === 'opened' || p === 'failed';
        }).length;
        if (total > 0 && settled >= total) return tr(PROGRESS_KEYS.checking, { total: total });
        return tr(PROGRESS_KEYS.header, { current: Math.min(total, settled + 1), total: total });
    }

    function progressWords(row) {
        if (!row) return '';
        if (row.phase === 'failed') {
            return tr(PROGRESS_KEYS.failed, { reason: row.detail || tr('restore_offer.row.failed_unsaid') });
        }
        return tr(PROGRESS_KEYS[row.phase] || PROGRESS_KEYS.queued);
    }

    function headline(reason, count, when, older) {
        var n = count + ' ' + plural(count, 'session', 'sessions');
        var were = plural(count, 'was', 'were');
        var at = when ? ' at ' + when : '';
        var plus = older ? ', plus ' + older + ' older' : '';
        if (reason === 'reboot') {
            return n + ' ' + were + ' open before the restart' + at + plus + '. reopen them?';
        }
        if (reason === 'tmux_server_gone') {
            return n + ' ' + were + ' open before the terminal server stopped' + at + plus + '. reopen them?';
        }
        if (reason === 'unknown_boot') {
            return n + ' ' + were + ' open and ' + plural(count, 'is', 'are') + ' not running now'
                + plus + '. reopen them?';
        }
        return n + ' stopped without being closed' + plus + '. reopen them?';
    }

    function headlineCounts(reason, items) {
        var older = items.filter(function (i) {
            return i.lost_reason && i.lost_reason !== reason;
        }).length;
        return { current: items.length - older, older: older };
    }

    function initialChecked(item) {
        return !!(item && item.selectable);
    }

    function headlineTime(offer, fmt) {
        var epoch = offer && offer.reason === 'reboot' && offer.boot_epoch
            ? offer.boot_epoch * 1000
            : (offer && offer.created_at ? Date.parse(offer.created_at) : NaN);
        if (!isFinite(epoch)) return '';
        return (fmt || defaultFormat)(new Date(epoch));
    }

    function defaultFormat(date) {
        try {
            return date.toLocaleString(undefined, {
                month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
            }).toLowerCase();
        } catch (err) {
            return date.toISOString();
        }
    }

    function ago(iso, nowMs) {
        var t = iso ? Date.parse(iso) : NaN;
        if (!isFinite(t)) return 'unknown';
        var s = Math.max(0, Math.round(((nowMs || Date.now()) - t) / 1000));
        if (s < 90) return 'just now';
        var m = Math.round(s / 60);
        if (m < 90) return m + ' min ago';
        var h = Math.round(m / 60);
        if (h < 36) return h + ' ' + plural(h, 'hour', 'hours') + ' ago';
        var d = Math.round(h / 24);
        return d + ' ' + plural(d, 'day', 'days') + ' ago';
    }

    function shortFolder(path) {
        if (!path) return 'unknown folder';
        var parts = String(path).split('/').filter(Boolean);
        return parts.slice(-2).join('/') || path;
    }

    function blockedWords(item) {
        if (!item || item.selectable) return '';
        return BLOCK_WORDS[item.blocked] || 'cannot be reopened';
    }

    function trustWords(item) {
        return item && item.folder_trust === 'will_ask' ? TRUST_NOTE : '';
    }

    function conversationWords(item) {
        if (!item.conversation) return 'none recorded';
        var text = item.conversation.slice(0, 8);
        if (item.conversation_recorded && item.conversation_recorded !== item.conversation) {
            text += ' (record says ' + item.conversation_recorded.slice(0, 8) + ')';
        }
        return text;
    }

    function dropWords(item, wrapperId) {
        var drops = (item.wrapper_drops || {})[wrapperId] || [];
        return drops.length ? 'comes back without ' + drops.join(' ') : '';
    }

    function selection(items, checked, wrappers) {
        return items.filter(function (it) {
            return it.selectable && checked[it.session_uuid];
        }).map(function (it) {
            return {
                session_uuid: it.session_uuid,
                agent_type: wrappers[it.session_uuid] || it.wrapper_default,
            };
        });
    }

    function rowHtml(item, nowMs) {
        var id = 'restore-offer-' + esc(item.session_uuid);
        var chosen = (item.wrapper_options || []).filter(function (o) { return o.id === item.wrapper_default; })[0];
        var chosenLabel = chosen ? (chosen.label || chosen.id) : (item.wrapper_default || 'choose');
        var blocked = blockedWords(item);
        var trust = item.selectable ? trustWords(item) : '';
        var how = item.kind === 'husk' ? 'restarts in its old pane' : '';
        var box = item.selectable ? (initialChecked(item) ? ' checked' : '') : ' disabled';
        return '<li class="restore-offer__row' + (item.selectable ? '' : ' is-blocked') + '" '
            + 'data-session-uuid="' + esc(item.session_uuid) + '">'
            + '<input type="checkbox" class="restore-offer__check" id="' + id + '"' + box + '>'
            + '<label class="restore-offer__main" for="' + id + '">'
            + '<span class="restore-offer__name">' + esc(item.title || item.tmux_name) + '</span>'
            + '<span class="restore-offer__meta" title="' + esc(item.folder) + '">'
            + esc(shortFolder(item.folder)) + ' &middot; conversation ' + esc(conversationWords(item))
            + ' &middot; active ' + esc(ago(item.last_work_at || item.last_seen_live, nowMs))
            + (how ? ' &middot; ' + esc(how) : '') + '</span>'
            + (blocked ? '<span class="restore-offer__blocked" title="' + esc(item.detail) + '">'
                + esc(blocked) + '</span>' : '')
            + (trust ? '<span class="restore-offer__trust">' + esc(trust) + '</span>' : '')
            + '<span class="restore-offer__drops" aria-live="polite"></span>'
            + '<span class="restore-offer__progress" aria-live="polite"></span>'
            + '</label>'
            + '<button type="button" class="restore-offer__wrapper oc-focus-host" aria-label="start it with"'
            + ' value="' + esc(item.wrapper_default || '') + '"'
            + ' data-allowed="' + esc((item.wrapper_options || []).map(function (o) { return o.id; }).join(',')) + '"'
            + (item.selectable ? '' : ' disabled') + '>' + esc(chosenLabel) + '</button>'
            + '</li>';
    }

    function panelHtml(offer, items, nowMs, fmt) {
        var selectable = items.filter(function (i) { return i.selectable; }).length;
        var counts = headlineCounts(offer.reason, items);
        return '<div class="modal-content restore-offer__content" role="dialog" aria-modal="true" '
            + 'aria-labelledby="restore-offer-title">'
            + '<div class="modal-titlerow restore-offer__head">'
            + '<span class="restore-offer__verb">&raquo; reopen sessions</span>'
            + '</div>'
            + '<div class="restore-offer__intro">'
            + '<div class="modal-message" id="restore-offer-title">'
            + esc(headline(offer.reason, counts.current, headlineTime(offer, fmt), counts.older)) + '</div>'
            + '<div class="modal-description">each one comes back on its own record with its '
            + 'conversation resumed. nothing opens until you press reopen.</div>'
            + '<label class="restore-offer__all oc-focus-host"><input type="checkbox" id="restore-offer-all"'
            + (selectable ? '' : ' disabled') + '> select all (' + selectable + ')</label>'
            + '</div>'
            + '<div class="restore-offer__scroll">'
            + '<ul class="restore-offer__rows">'
            + items.map(function (it) { return rowHtml(it, nowMs); }).join('')
            + '</ul>'
            + '</div>'
            + '<div class="restore-offer__status" aria-live="polite"></div>'
            + '<div class="modal-footer restore-offer__footer">'
            + '<button type="button" class="modal-btn modal-btn-secondary" id="restore-offer-no">not now</button>'
            + '<button type="button" class="modal-btn modal-btn-primary" id="restore-offer-go"'
            + (selectable ? '' : ' disabled') + '>reopen selected</button>'
            + '</div></div>';
    }

    var releaseTrap = function () {};

    function close() {
        if (overlayEl && overlayEl.parentNode) overlayEl.parentNode.removeChild(overlayEl);
        overlayEl = null;
        releaseTrap();
        releaseTrap = function () {};
    }

    function render(api, offer, items) {
        close();
        shownIds[offer.id] = true;
        var overlay = document.createElement('div');
        overlay.className = 'modal-overlay restore-offer';
        overlay.innerHTML = panelHtml(offer, items, Date.now());
        document.body.appendChild(overlay);
        overlayEl = overlay;
        var byUuid = {};
        items.forEach(function (it) { byUuid[it.session_uuid] = it; });
        var checks = Array.prototype.slice.call(overlay.querySelectorAll('.restore-offer__check'));
        var all = overlay.querySelector('#restore-offer-all');
        var go = overlay.querySelector('#restore-offer-go');
        var no = overlay.querySelector('#restore-offer-no');
        var status = overlay.querySelector('.restore-offer__status');

        releaseTrap = window.ModalStack && typeof window.ModalStack.trap === 'function'
            ? window.ModalStack.trap(overlay, {
                onEscape: function () {
                    if (overlay.querySelector('#restore-offer-done')) close();
                    else if (!no.disabled) no.click();
                },
            })
            : function () {};

        function checkedMap() {
            var map = {};
            checks.forEach(function (c) {
                map[c.closest('.restore-offer__row').dataset.sessionUuid] = c.checked && !c.disabled;
            });
            return map;
        }
        function wrapperMap() {
            var map = {};
            overlay.querySelectorAll('.restore-offer__row').forEach(function (row) {
                map[row.dataset.sessionUuid] = row.querySelector('.restore-offer__wrapper').value;
            });
            return map;
        }
        function sync() {
            var live = checks.filter(function (c) { return !c.disabled; });
            var on = live.filter(function (c) { return c.checked; }).length;
            if (all) {
                all.checked = live.length > 0 && on === live.length;
                all.indeterminate = on > 0 && on < live.length;
            }
            go.disabled = on === 0;
        }
        if (all) {
            all.addEventListener('change', function () {
                checks.forEach(function (c) { if (!c.disabled) c.checked = all.checked; });
                sync();
            });
        }
        checks.forEach(function (c) { c.addEventListener('change', sync); });
        overlay.querySelectorAll('.restore-offer__row').forEach(function (row) {
            var select = row.querySelector('.restore-offer__wrapper');
            var note = row.querySelector('.restore-offer__drops');
            var update = function () { note.textContent = dropWords(byUuid[row.dataset.sessionUuid], select.value); };
            select.addEventListener('click', function () {
                var web = window.CloudeWeb;
                if (!web || typeof web.openLaunchPicker !== 'function') return;
                var allowed = select.dataset.allowed ? select.dataset.allowed.split(',') : null;
                web.openLaunchPicker({ preselect: select.value, onlyIds: allowed, accounts: false }).then(function (pick) {
                    if (!pick) return;
                    select.value = pick.profileId;
                    select.textContent = pick.profileLabel || pick.profileId;
                    update();
                });
            });
            update();
        });
        no.addEventListener('click', function () {
            no.disabled = true;
            api.call(ENDPOINT + '/decline', { method: 'POST', body: { offer_id: offer.id } })
                .catch(function (err) { console.warn('restore offer: decline failed', err); })
                .finally(close);
        });
        go.addEventListener('click', function () {
            var chosen = selection(items, checkedMap(), wrapperMap());
            if (!chosen.length) return;
            go.disabled = true;
            no.disabled = true;
            overlay.querySelectorAll('input, select, button.restore-offer__wrapper').forEach(function (el) { el.disabled = true; });
            var progress = progressStart(chosen);
            var paint = function () {
                status.textContent = progressHeader(progress);
                progress.order.forEach(function (id) {
                    var row = overlay.querySelector('.restore-offer__row[data-session-uuid="' + CSS.escape(id) + '"]');
                    var slot = row && row.querySelector('.restore-offer__progress');
                    if (!slot) return;
                    slot.dataset.phase = progress.rows[id].phase;
                    slot.textContent = progressWords(progress.rows[id]);
                });
            };
            var events = globalThis.AppEvents;
            var unsubscribe = events && typeof events.subscribe === 'function'
                ? events.subscribe(function (frame) { if (applyProgress(progress, offer.id, frame)) paint(); })
                : function () {};
            paint();
            api.call(ENDPOINT + '/accept', {
                method: 'POST', body: { offer_id: offer.id, sessions: chosen }, expectedStatuses: [409],
            })
                .then(function (res) { unsubscribe(); showResults(overlay, (res && res.results) || []); })
                .catch(function (err) {
                    unsubscribe();
                    if (err && err.status === 409) {
                        close();
                        check(api);
                        return;
                    }
                    status.textContent = tr('restore_offer.reopen_failed', { reason: (err && err.message) || err });
                    no.disabled = false;
                });
        });
        sync();
    }

    function resultWords(r) {
        if (r.outcome === 'reopened') {
            return r.startup_gate === GATE_AWAITING && r.detail ? r.detail : 'reopened';
        }
        return (r.outcome || 'failed') + (r.detail ? ': ' + r.detail : '');
    }

    function summaryWords(results) {
        var ok = results.filter(function (r) { return r.outcome === 'reopened'; });
        var waiting = ok.filter(function (r) { return r.startup_gate === GATE_AWAITING; }).length;
        return ok.length + ' of ' + results.length + ' reopened'
            + (waiting ? ', ' + waiting + ' waiting on the folder trust prompt' : '');
    }

    function resultsHtml(results) {
        return '<ul class="restore-offer__results">' + results.map(function (r) {
            var waiting = r.outcome === 'reopened' && r.startup_gate === GATE_AWAITING;
            return '<li class="restore-offer__result is-' + esc(r.outcome) + (waiting ? ' is-waiting' : '') + '">'
                + '<span class="restore-offer__name">' + esc(r.title || r.session_uuid) + '</span>'
                + '<span class="restore-offer__result-words">' + esc(resultWords(r)) + '</span></li>';
        }).join('') + '</ul>';
    }

    function showResults(overlay, results) {
        var intro = overlay.querySelector('.restore-offer__intro');
        intro.innerHTML = '<div class="modal-message restore-offer__summary" id="restore-offer-title">'
            + esc(summaryWords(results)) + '</div>';
        var scroll = overlay.querySelector('.restore-offer__scroll');
        scroll.innerHTML = resultsHtml(results);
        scroll.scrollTop = 0;
        overlay.querySelector('.restore-offer__status').textContent = '';
        var footer = overlay.querySelector('.modal-footer');
        footer.innerHTML = '<button type="button" class="modal-btn modal-btn-primary" id="restore-offer-done">done</button>';
        var done = footer.querySelector('#restore-offer-done');
        done.addEventListener('click', close);
        done.focus();
    }

    function check(api) {
        if (!api || typeof api.call !== 'function') return Promise.resolve(null);
        return api.call(ENDPOINT).then(function (res) {
            var items = (res && res.sessions) || [];
            if (res && res.offer && items.length && !overlayEl && !shownIds[res.offer.id]) {
                render(api, res.offer, items);
            }
            return res;
        }).catch(function (err) {
            console.warn('restore offer: check failed', err);
            return null;
        });
    }

    function start(api) {
        if (started) return;
        started = true;
        var client = api || window.API;
        setTimeout(function () { check(client); }, FIRST_CHECK_DELAY_MS);
        var recheck = function () {
            if (typeof document !== 'undefined' && document.hidden) return;
            check(client);
        };
        var push = globalThis.ResourcePush;
        if (push && typeof push.pushOrPoll === 'function') {
            push.pushOrPoll(recheck, RECHECK_INTERVAL_MS, ['restore_offer']);
        } else {
            setInterval(recheck, RECHECK_INTERVAL_MS);
        }
    }

    var exported = {
        headline: headline,
        headlineCounts: headlineCounts,
        headlineTime: headlineTime,
        initialChecked: initialChecked,
        ago: ago,
        shortFolder: shortFolder,
        blockedWords: blockedWords,
        trustWords: trustWords,
        conversationWords: conversationWords,
        dropWords: dropWords,
        selection: selection,
        panelHtml: panelHtml,
        progressStart: progressStart,
        applyProgress: applyProgress,
        progressHeader: progressHeader,
        progressWords: progressWords,
        resultWords: resultWords,
        summaryWords: summaryWords,
        resultsHtml: resultsHtml,
        showResults: showResults,
        render: render,
        check: check,
        start: start,
    };
    if (typeof window !== 'undefined') window.SessionRestoreOffer = exported;
    if (typeof globalThis !== 'undefined') globalThis.SessionRestoreOffer = exported;
})();
