
console.log('[SessionRestartOptions Module] Loading...');

(function () {
    'use strict';

    var KIND_TAG = {
        agent: '',
        replay: 'session.restart.kind.replay',
        shell: 'session.restart.kind.shell',
        not_dead: 'session.restart.kind.not_dead',
        transcript_missing: 'session.restart.kind.transcript_missing',
        cannot_determine: 'session.restart.kind.cannot_determine',
        recreate: 'session.restart.kind.recreate',
    };

    var ACTIONABLE = ['agent', 'replay', 'shell', 'recreate'];
    var NO_CHOICE = '__none__';

    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key, params) : key;
    }

    function kindTag(kind) {
        var key = Object.prototype.hasOwnProperty.call(KIND_TAG, kind)
            ? KIND_TAG[kind] : KIND_TAG.cannot_determine;
        return key ? tr(key) : '';
    }

    function esc(value) {
        var controls = window.SessionSidebarRowControls;
        if (controls && typeof controls.escHtml === 'function') return controls.escHtml(value);
        var div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML.replace(/"/g, '&quot;');
    }

    function isActionable(kind) {
        return ACTIONABLE.indexOf(kind) !== -1;
    }

    /* could not be determined */
    function rowFacts(preview) {
        var unchanged = (preview && preview.unchanged) || {};
        var projected = (preview && preview.projected) || {};
        var facts = [{
            detail: projected.detail || unchanged.detail
                || 'what this would run could not be determined',
            kind: projected.kind || unchanged.kind || 'cannot_determine',
        }];
        ((preview && preview.options) || []).forEach(function (o) {
            facts.push({
                detail: (o && (o.projected_detail || o.detail)) || '',
                kind: (o && (o.projected_kind || o.kind)) || 'cannot_determine',
            });
        });
        return facts;
    }

    function sharedDetail(preview) {
        var facts = rowFacts(preview);
        var none = { detail: '', kind: '' };
        if (facts.length < 2) return none;
        var first = facts[0];
        if (!first.detail) return none;
        for (var i = 1; i < facts.length; i += 1) {
            if (facts[i].detail !== first.detail) return none;
            if (facts[i].kind !== first.kind) return none;
        }
        return { detail: first.detail, kind: first.kind };
    }

    function sharedDetailHtml(preview) {
        var shared = sharedDetail(preview);
        if (!shared.detail) return '';
        if (shared.kind !== 'transcript_missing') {
            return '<div class="restart-picker__shared">'
                + esc(shared.detail) + '</div>';
        }
        return '<div class="restart-picker__shared" '
            + 'data-kind="transcript_missing">'
            + '<span class="restart-picker__shared-line">'
            + esc(tr('session.restart.picker.gone'))
            + '</span>'
            + '<details class="restart-picker__shared-more">'
            + '<summary>' + esc(tr('session.restart.picker.gone.more'))
            + '</summary>'
            + '<span>' + esc(shared.detail) + '</span>'
            + '</details>'
            + '</div>';
    }

    function commonKind(preview) {
        var facts = rowFacts(preview);
        if (facts.length < 2) return '';
        for (var i = 1; i < facts.length; i += 1) {
            if (facts[i].kind !== facts[0].kind) return '';
        }
        return facts[0].kind;
    }

    function splitLabel(label) {
        var text = label == null ? '' : String(label);
        var m = /^(.+?)\s*\(([^()]+)\)$/.exec(text);
        return m ? { name: m[1], tag: m[2] } : { name: text, tag: '' };
    }

    function optionRow(id, value, title, spec, hide) {
        var kind = spec.projectedKind || spec.kind || 'cannot_determine';
        var canPick = spec.actionableNow === true && isActionable(spec.kind);
        var liveEligible = isActionable(spec.projectedKind || spec.kind);
        var parts = splitLabel(title);
        var detail = spec.detail || '';
        var tags = [];
        if (parts.tag) tags.push(parts.tag);
        if (spec.launched) tags.push(tr('session.restart.picker.launched_with'));
        if (spec.current) tags.push(tr('session.restart.picker.current'));
        var mark = spec.mark || {};
        return {
            value: value,
            id: id,
            label: parts.name,
            harness: mark.family || '',
            icon: mark.icon || null,
            account: '',
            model: '',
            modelMode: 'default',
            badge: '',
            permissions: '',
            isDefault: false,
            connectionId: null,
            tags: tags,
            kind: kind,
            kindTag: kind !== hide.kind ? kindTag(kind) : '',
            detail: '',
            hint: detail && detail !== hide.detail ? detail : '',
            enrichFrom: spec.enrichFrom || value,
            disabled: !canPick,
            data: {
                'kind': kind,
                'now-kind': spec.kind || '',
                'actionable-now': canPick ? '1' : '0',
                'live-eligible': liveEligible ? '1' : '0',
                'family': mark.family || '',
                'launched': spec.launched ? '1' : '',
            },
        };
    }

    function optionRows(preview) {
        var unchanged = preview.unchanged || {};
        var projected = preview.projected || {};
        var hide = {
            detail: sharedDetail(preview).detail,
            kind: commonKind(preview),
        };
        var merged = (preview.options || []).filter(function (o) {
            return o.same_as_unchanged === true;
        })[0] || null;
        var launchedOption = (preview.options || []).filter(function (o) {
            return o.agent_type === preview.current_agent_type && o.label;
        })[0] || null;
        var anyStartable = (preview.options || []).some(function (o) {
            return o.actionable_now === true;
        });
        var baselineOut = preview.pane_state !== 'alive'
            && unchanged.actionable !== true && anyStartable;
        var hideRefused = baselineOut;
        var keepValue = merged && unchanged.kind === 'recreate'
            ? merged.agent_type : '';
        var out = baselineOut ? [] : [
            optionRow('restart-choice-keep', keepValue,
                (launchedOption && launchedOption.label)
                    || preview.current_agent_type
                    || tr('session.restart.picker.as_launched'), {
                    kind: unchanged.kind || 'cannot_determine',
                    projectedKind: projected.kind || unchanged.kind
                        || 'cannot_determine',
                    detail: projected.detail || unchanged.detail
                        || 'what this would run could not be determined',
                    actionableNow: unchanged.actionable === true,
                    launched: !!preview.current_agent_type,
                    current: !!merged,
                    mark: merged
                        ? { icon: merged.icon || null, family: merged.family || null }
                        : null,
                    enrichFrom: preview.current_agent_type || '__none__',
                }, hide),
        ];
        (preview.options || []).forEach(function (o, i) {
            if (o.same_as_unchanged === true) return;
            if (hideRefused && o.actionable_now !== true) return;
            out.push(optionRow(
                'restart-choice-' + i,
                o.agent_type,
                o.label || o.agent_type,
                {
                    kind: o.kind,
                    projectedKind: o.projected_kind || o.kind,
                    detail: o.projected_detail || o.detail,
                    actionableNow: o.actionable_now === true,
                    mark: { icon: o.icon || null, family: o.family || null },
                    current: !!o.is_current,
                    launched: baselineOut && !!preview.current_agent_type
                        && o.agent_type === preview.current_agent_type,
                },
                hide
            ));
        });
        return out;
    }

    /* the launch choice */
    function mountChoice(containerId, preview, accounts) {
        var web = globalThis.CloudeWeb;
        if (!web || typeof web.mountLaunchChoice !== 'function') return null;
        var rows = optionRows(preview);
        var keep = rows.filter(function (r) { return r.id === 'restart-choice-keep'; })[0];
        var recorded = rows.filter(function (r) {
            return r.data.launched === '1' && !r.disabled;
        })[0] || null;
        return web.mountLaunchChoice(containerId, {
            rows: rows,
            value: keep ? keep.value : (recorded ? recorded.value : NO_CHOICE),
            label: tr('session.restart.picker.options'),
            accounts: accounts || null,
        });
    }

    function accountsFor(sessionUuid) {
        if (!sessionUuid || !window.API || !window.API.restartAccounts) {
            return Promise.resolve(null);
        }
        return window.API.restartAccounts(sessionUuid).then(function (answer) {
            return answer && answer.options && answer.options.length ? answer : null;
        }).catch(function (err) {
            console.warn('SessionRestartOptions: accounts unavailable:', err);
            return null;
        });
    }

    /* could not */
    function shouldRecreate(preview) {
        if (!preview) return false;
        if (preview.pane_state === 'alive') return false;
        var unchanged = preview.unchanged || {};
        return unchanged.kind === 'cannot_determine';
    }


    function previewFor(tmuxName, sessionUuid) {
        return window.API.restartPreview(tmuxName).then(function (preview) {
            if (!shouldRecreate(preview) || !sessionUuid
                || !window.API.recreatePreview) {
                return { preview: preview, mode: 'restart', sessionUuid: null };
            }
            return window.API.recreatePreview(sessionUuid)
                .then(function (recreated) {
                    return {
                        preview: recreated,
                        mode: 'recreate',
                        sessionUuid: sessionUuid,
                    };
                })
                .catch(function (err) {
                    console.warn(
                        'SessionRestartOptions: recreate preview failed:', err);
                    return { preview: preview, mode: 'restart', sessionUuid: null };
                });
        });
    }

    function recreateTarget(records, tmuxName) {
        if (!tmuxName || !records || !records.length) return null;
        var hits = [];
        for (var i = 0; i < records.length; i += 1) {
            var r = records[i];
            if (r && r.tmux_name === tmuxName && r.session_uuid) {
                hits.push(r.session_uuid);
            }
        }
        return hits.length === 1 ? hits[0] : null;
    }

    window.SessionRestartOptions = {
        KIND_TAG: KIND_TAG,
        kindTag: kindTag,
        tr: tr,
        esc: esc,
        isActionable: isActionable,
        rowFacts: rowFacts,
        sharedDetail: sharedDetail,
        sharedDetailHtml: sharedDetailHtml,
        commonKind: commonKind,
        splitLabel: splitLabel,
        optionRows: optionRows,
        mountChoice: mountChoice,
        accountsFor: accountsFor,
        shouldRecreate: shouldRecreate,
        previewFor: previewFor,
        recreateTarget: recreateTarget,
    };
})();

console.log('[SessionRestartOptions Module] Exported as window.SessionRestartOptions');
