/* could not be read */

console.log('[ThemeConsent Module] Loading...');

(function () {
    const FIELD = 'theme_script_consent';

    const LEGACY_KEY = 'cloude.themeJsAllowlist';

    const DECISION_ALWAYS = 'always';
    const DECISION_NEVER = 'never';
    const DECISION_ONCE = 'once';

    const SOURCE_BUILTIN = 'builtin';
    const SOURCE_USER = 'user';

    const RUN = 'run';
    const SKIP_NO_SCRIPT = 'skip_no_script';
    const SKIP_DENIED = 'skip_denied';
    const SKIP_DENIED_UNSAVED = 'skip_denied_unsaved';
    const SKIP_UNVERIFIABLE = 'skip_unverifiable';
    const PROMPT = 'prompt';
    const PROMPT_CHANGED = 'prompt_changed';

    const RUNG_NO_SCRIPT = 'no_script';
    const RUNG_DENIED = 'denied';
    const RUNG_RECORD_UNREADABLE = 'record_unreadable';
    const RUNG_BUILTIN = 'builtin';
    const RUNG_FIRST_PARTY = 'first_party';
    const RUNG_DIGEST_UNAVAILABLE = 'digest_unavailable';
    const RUNG_DIGEST_MISMATCH = 'digest_mismatch';
    const RUNG_GRANTED = 'granted';
    const RUNG_NO_RECORD = 'no_record';

    const DIGEST_RE = /^[0-9a-f]{64}$/;


    const PERSISTED_STATUSES = ['committed', 'unchanged'];

    /* could not */
    function decide(input) {
        const spec = input || {};
        if (!spec.declaresScript) {
            return result(SKIP_NO_SCRIPT, RUNG_NO_SCRIPT, null);
        }

        const record = (spec.record && typeof spec.record === 'object')
            ? spec.record : null;
        const decision = record ? record.decision : null;
        const served = typeof spec.servedDigest === 'string'
            ? spec.servedDigest : null;

        if (decision === DECISION_NEVER) {
            return result(SKIP_DENIED, RUNG_DENIED, served);
        }
        if (spec.recordReadable === false) {
            return result(SKIP_UNVERIFIABLE, RUNG_RECORD_UNREADABLE, served);
        }
        if (spec.source === SOURCE_BUILTIN) {
            return result(RUN, RUNG_BUILTIN, served);
        }
        if (spec.source === SOURCE_USER && spec.scriptTrust === 'first_party') {
            return result(RUN, RUNG_FIRST_PARTY, served);
        }
        if (!served || !DIGEST_RE.test(served)) {
            return result(SKIP_UNVERIFIABLE, RUNG_DIGEST_UNAVAILABLE, null);
        }
        if (decision === DECISION_ALWAYS) {
            if (typeof record.digest === 'string' && record.digest === served) {
                return result(RUN, RUNG_GRANTED, served);
            }
            return result(PROMPT_CHANGED, RUNG_DIGEST_MISMATCH, served);
        }
        return result(PROMPT, RUNG_NO_RECORD, served);
    }

    function result(outcome, rung, digest) {
        return { outcome: outcome, rung: rung, digest: digest || null };
    }

    function recordFor(decision, digest) {
        if (decision === DECISION_NEVER) {
            return { decision: DECISION_NEVER };
        }
        if (decision === DECISION_ALWAYS) {
            if (typeof digest === 'string' && DIGEST_RE.test(digest)) {
                return { decision: DECISION_ALWAYS, digest: digest };
            }
            return null;
        }
        return null;
    }

    /* not allowed */
    function revocationsBetween(before, after) {
        const prior = (before && typeof before === 'object') ? before : {};
        const current = (after && typeof after === 'object') ? after : {};
        const moved = [];
        Object.keys(current).forEach(function (id) {
            const entry = current[id];
            if (!entry || entry.decision !== DECISION_NEVER) return;
            const was = prior[id];
            if (was && was.decision === DECISION_NEVER) return;
            moved.push(id);
        });
        return moved.sort();
    }

    function readRecord() {
        const legacy = readLegacyRefusals();
        const prefs = globalThis.Preferences;
        if (!prefs || typeof prefs.get !== 'function') {
            return { map: legacy, readable: false };
        }
        if (typeof prefs.status === 'function' && prefs.status() !== prefs.HYDRATED) {
            return { map: legacy, readable: false };
        }
        const shared = prefs.get(FIELD, null);
        const map = Object.create(null);
        Object.keys(legacy).forEach(function (id) { map[id] = legacy[id]; });
        if (shared && typeof shared === 'object') {
            Object.keys(shared).forEach(function (id) {
                const entry = shared[id];
                if (!entry || typeof entry !== 'object') return;
                if (map[id] && map[id].decision === DECISION_NEVER) return;
                map[id] = entry;
            });
        }
        return { map: map, readable: true };
    }

    function readLegacyRefusals() {
        const out = Object.create(null);
        let raw;
        try {
            raw = globalThis.localStorage
                ? globalThis.localStorage.getItem(LEGACY_KEY) : null;
        } catch (err) {
            return out;
        }
        if (!raw) return out;
        let parsed;
        try {
            parsed = JSON.parse(raw);
        } catch (err) {
            return out;
        }
        if (!parsed || typeof parsed !== 'object') return out;
        Object.keys(parsed).forEach(function (id) {
            if (parsed[id] === false) out[id] = { decision: DECISION_NEVER };
        });
        return out;
    }

    function entryFor(themeId) {
        const held = readRecord();
        if (!held.readable) return null;
        return held.map[themeId] || null;
    }

    /* nothing at all */
    async function remember(themeId, decision, digest) {
        const entry = recordFor(decision, digest);
        if (!entry) return { status: 'not_stored' };

        const prefs = globalThis.Preferences;
        if (!prefs || typeof prefs.set !== 'function') {
            return { status: 'refused', detail: 'preferences are unavailable' };
        }
        const current = prefs.get(FIELD, null);
        const next = {};
        if (current && typeof current === 'object') {
            Object.keys(current).forEach(function (id) { next[id] = current[id]; });
        }
        next[themeId] = entry;
        return prefs.set(FIELD, next);
    }

    /* could not be written */
    const UNSAVED_REFUSAL_COPY = 'this theme\'s script is blocked for now, but '
        + 'the choice could not be saved. you will be asked again next time.';

    function persisted(outcome) {
        if (!outcome || typeof outcome.status !== 'string') return false;
        return PERSISTED_STATUSES.indexOf(outcome.status) !== -1;
    }

    /* could not */
    function report(spec, message, info) {
        console.warn('[ThemeConsent] ' + message, info);
        const notify = (spec && typeof spec.notify === 'function')
            ? spec.notify : null;
        if (!notify) return;
        try {
            notify(message, info);
        } catch (err) {
            console.warn('[ThemeConsent] could not report to the user', err);
        }
    }

    async function gateEffects(spec) {
        const manifest = (spec && spec.manifest) || null;
        const inject = (spec && typeof spec.inject === 'function') ? spec.inject : null;
        const prompt = (spec && typeof spec.prompt === 'function') ? spec.prompt : null;
        if (!manifest || !inject) return SKIP_UNVERIFIABLE;

        const held = readRecord();
        const verdict = decide({
            declaresScript: !!manifest.effects,
            source: manifest.source,
            servedDigest: manifest.effectsDigest,
            record: held.map[manifest.id] || null,
            recordReadable: held.readable,
            scriptTrust: manifest.scriptTrust,
        });

        if (verdict.outcome === RUN) {
            inject(manifest);
            return RUN;
        }
        if (verdict.outcome !== PROMPT && verdict.outcome !== PROMPT_CHANGED) {
            if (verdict.outcome !== SKIP_NO_SCRIPT) {
                console.log('[ThemeConsent] effects skipped for ' + manifest.id
                    + ' (' + verdict.rung + ')');
            }
            return verdict.outcome;
        }
        if (!prompt) return SKIP_UNVERIFIABLE;

        let answer;
        try {
            answer = await prompt(manifest, {
                changed: verdict.outcome === PROMPT_CHANGED,
                digest: verdict.digest,
            });
        } catch (err) {
            console.warn('[ThemeConsent] prompt failed, refusing', err);
            return SKIP_UNVERIFIABLE;
        }

        if (answer === DECISION_NEVER) {
            const kept = await remember(manifest.id, DECISION_NEVER, null);
            if (!persisted(kept)) {
                report(spec, UNSAVED_REFUSAL_COPY, {
                    themeId: manifest.id,
                    status: (kept && kept.status) || 'unknown',
                    detail: (kept && kept.detail) || null,
                });
                return SKIP_DENIED_UNSAVED;
            }
            return SKIP_DENIED;
        }
        if (answer === DECISION_ONCE) {
            inject(manifest);
            return RUN;
        }
        if (answer !== DECISION_ALWAYS) {
            return SKIP_UNVERIFIABLE;
        }

        const saved = await remember(manifest.id, DECISION_ALWAYS, verdict.digest);
        if (saved && saved.status === 'stale_revision') {
            const again = readRecord();
            const second = decide({
                declaresScript: true,
                source: manifest.source,
                servedDigest: manifest.effectsDigest,
                record: again.map[manifest.id] || null,
                recordReadable: again.readable,
                scriptTrust: manifest.scriptTrust,
            });
            if (second.outcome !== RUN) return second.outcome;
        }
        inject(manifest);
        return RUN;
    }

    function watch() {
        if (watching) return true;
        const prefs = globalThis.Preferences;
        if (!prefs || typeof prefs.subscribe !== 'function') return false;
        lastSeen = snapshot();
        prefs.subscribe(function (name) {
            if (name !== FIELD) return;
            const now = snapshot();
            const revoked = revocationsBetween(lastSeen, now);
            lastSeen = now;
            if (!revoked.length) return;
            const themes = globalThis.Themes;
            if (!themes || typeof themes.revokeEffects !== 'function') return;
            revoked.forEach(function (id) {
                try {
                    themes.revokeEffects(id);
                } catch (err) {
                    console.warn('[ThemeConsent] teardown threw for ' + id, err);
                }
            });
        });
        watching = true;
        return true;
    }

    let watching = false;
    let lastSeen = Object.create(null);

    function snapshot() {
        const prefs = globalThis.Preferences;
        if (!prefs || typeof prefs.get !== 'function') return Object.create(null);
        const held = prefs.get(FIELD, null);
        return (held && typeof held === 'object') ? held : Object.create(null);
    }

    const api = {
        FIELD: FIELD,
        LEGACY_KEY: LEGACY_KEY,
        DECISION_ALWAYS: DECISION_ALWAYS,
        DECISION_NEVER: DECISION_NEVER,
        DECISION_ONCE: DECISION_ONCE,
        RUN: RUN,
        SKIP_NO_SCRIPT: SKIP_NO_SCRIPT,
        SKIP_DENIED: SKIP_DENIED,
        SKIP_DENIED_UNSAVED: SKIP_DENIED_UNSAVED,
        SKIP_UNVERIFIABLE: SKIP_UNVERIFIABLE,
        UNSAVED_REFUSAL_COPY: UNSAVED_REFUSAL_COPY,
        PROMPT: PROMPT,
        PROMPT_CHANGED: PROMPT_CHANGED,
        RUNG_DENIED: RUNG_DENIED,
        RUNG_RECORD_UNREADABLE: RUNG_RECORD_UNREADABLE,
        RUNG_BUILTIN: RUNG_BUILTIN,
        RUNG_FIRST_PARTY: RUNG_FIRST_PARTY,
        RUNG_DIGEST_UNAVAILABLE: RUNG_DIGEST_UNAVAILABLE,
        RUNG_DIGEST_MISMATCH: RUNG_DIGEST_MISMATCH,
        RUNG_GRANTED: RUNG_GRANTED,
        RUNG_NO_RECORD: RUNG_NO_RECORD,
        RUNG_NO_SCRIPT: RUNG_NO_SCRIPT,
        decide: decide,
        persisted: persisted,
        recordFor: recordFor,
        revocationsBetween: revocationsBetween,
        readRecord: readRecord,
        entryFor: entryFor,
        remember: remember,
        gateEffects: gateEffects,
        watch: watch,
    };

    globalThis.ThemeConsent = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    watch();

    console.log('[ThemeConsent Module] Loaded');
})();
