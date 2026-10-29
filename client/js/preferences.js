
console.log('[Preferences Module] Loading...');

(function () {
    /** @type {string} Hydration has not run. Nothing may be saved. */
    const NOT_HYDRATED = 'not_hydrated';

    /** @type {string} The block was read; values are authoritative. */
    const HYDRATED = 'hydrated';

    /** @type {string} A read was attempted and failed. Saving stays
     * refused: writing now would push this browser's defaults over
     * settings we were unable to see. */
    const READ_FAILED = 'read_failed';

    /** @type {string} This field matches what the server committed. */
    const COMMITTED = 'committed';

    /** @type {string} The user changed it; the save is in flight. */
    const PENDING = 'pending';

    /** @type {string} The save was attempted and did not land. The
     * user's value is still on screen and can be retried. */
    const FAILED = 'failed';

    /** @type {string} A newer committed value arrived for a field this
     * browser has an unsaved edit on. Both are kept. */
    const CONFLICT = 'conflict';

    const ENDPOINT = '/preferences';

    const clientId = 'c' + Math.random().toString(36).slice(2, 12);

    /** @type {{status: string, revision: number, values: object}} */
    const held = { status: NOT_HYDRATED, revision: 0, values: {} };

    const fields = Object.create(null);

    /** @type {Array<function(string, *, object): void>} */
    const listeners = [];

    let applyingRemote = false;

    function get(name, fallback) {
        const record = fields[name];
        if (record && (record.state === PENDING || record.state === FAILED
                       || record.state === CONFLICT)) {
            return record.local;
        }
        if (held.status !== HYDRATED) return fallback;
        if (Object.prototype.hasOwnProperty.call(held.values, name)) {
            return held.values[name];
        }
        return fallback;
    }

    function committedValue(name) {
        const record = fields[name];
        if (record && record.state === CONFLICT) return record.committed;
        return held.values[name];
    }

    function stateFor(name) {
        const record = fields[name];
        return record ? record.state : COMMITTED;
    }

    function status() {
        return held.status;
    }

    function revision() {
        return held.revision;
    }

    async function hydrate(api) {
        const client = api || globalThis.API;
        if (!client || typeof client.call !== 'function') {
            held.status = READ_FAILED;
            return held.status;
        }
        let body;
        try {
            body = await client.call(ENDPOINT);
        } catch (err) {
            console.warn('[Preferences] hydrate failed', err);
            held.status = READ_FAILED;
            return held.status;
        }
        const incoming = body && typeof body === 'object' ? Number(body.revision) : NaN;
        if (held.status === HYDRATED && Number.isFinite(incoming) && incoming < held.revision) {
            return held.status;
        }
        adoptServerState(body);
        held.status = HYDRATED;
        reconcileAfterRefresh();
        return held.status;
    }

    function reconcileAfterRefresh() {
        Object.keys(fields).forEach(function (name) {
            const record = fields[name];
            if (!record || record.state !== FAILED) return;
            if (held.values[name] === record.local) {
                delete fields[name];
                notify(name, held.values[name], { state: COMMITTED });
                return;
            }
            markConflict(name, record.local);
        });
    }

    async function set(name, value, api) {
        return await setMany({ [name]: value }, api);
    }

    async function setMany(changes, api) {
        if (applyingRemote) {
            return { status: 'refused', detail: 'applying a received change' };
        }
        if (held.status !== HYDRATED) {
            return { status: 'refused', detail: 'preferences have not been read yet' };
        }
        const client = api || globalThis.API;
        if (!client || typeof client.call !== 'function') {
            return { status: 'refused', detail: 'no api client' };
        }

        const names = Object.keys(changes);
        const previouslyCommitted = {};
        names.forEach(function (name) {
            previouslyCommitted[name] = held.values[name];
            fields[name] = { state: PENDING, local: changes[name], committed: previouslyCommitted[name] };
            notify(name, changes[name], fields[name]);
        });

        let body;
        try {
            body = await client.call(ENDPOINT, {
                method: 'PATCH',
                expectedStatuses: [409],
                body: {
                    changes: changes,
                    expected_revision: held.revision,
                    client_id: clientId,
                },
            });
        } catch (err) {
            const conflict = conflictBodyFrom(err);
            if (conflict) {
                adoptServerState(conflict);
                names.forEach(function (name) { markConflict(name, changes[name]); });
                return { status: 'stale_revision', detail: conflict.detail };
            }
            names.forEach(function (name) {
                fields[name] = {
                    state: FAILED, local: changes[name], committed: previouslyCommitted[name],
                };
                notify(name, changes[name], fields[name]);
            });
            return { status: 'failed', detail: String(err && err.message ? err.message : err) };
        }

        adoptServerState(body);
        names.forEach(function (name) {
            delete fields[name];
            notify(name, held.values[name], { state: COMMITTED });
        });
        return { status: body && body.status ? body.status : 'committed' };
    }

    function applyRemote(frame) {
        if (!frame || typeof frame !== 'object') return false;
        if (frame.origin_client_id && frame.origin_client_id === clientId) return false;

        const nextRevision = Number(frame.revision);
        if (!Number.isFinite(nextRevision) || nextRevision <= held.revision) {
            return false;
        }
        const changed = frame.changed && typeof frame.changed === 'object'
            ? frame.changed
            : {};

        held.revision = nextRevision;
        applyingRemote = true;
        try {
            Object.keys(changed).forEach(function (name) {
                const value = changed[name];
                if (value === null) {
                    delete held.values[name];
                } else {
                    held.values[name] = value;
                }
                const record = fields[name];
                if (record && (record.state === PENDING || record.state === FAILED)) {
                    markConflict(name, record.local);
                    return;
                }
                if (!record || record.state !== CONFLICT) {
                    notify(name, value, { state: COMMITTED });
                }
            });
        } finally {
            applyingRemote = false;
        }
        return true;
    }

    async function retry(name, api) {
        const record = fields[name];
        if (!record || record.state === COMMITTED) {
            return { status: 'refused', detail: 'nothing to retry' };
        }
        const value = record.local;
        delete fields[name];
        return await set(name, value, api);
    }

    function discardLocal(name) {
        if (!fields[name]) return;
        delete fields[name];
        notify(name, held.values[name], { state: COMMITTED });
    }

    function subscribe(listener) {
        if (typeof listener !== 'function') return function () {};
        listeners.push(listener);
        return function () {
            const at = listeners.indexOf(listener);
            if (at >= 0) listeners.splice(at, 1);
        };
    }

    function reset() {
        held.status = NOT_HYDRATED;
        held.revision = 0;
        held.values = {};
        Object.keys(fields).forEach(function (name) { delete fields[name]; });
        applyingRemote = false;
    }


    function adoptServerState(body) {
        if (!body || typeof body !== 'object') return;
        const nextRevision = Number(body.revision);
        if (Number.isFinite(nextRevision)) held.revision = nextRevision;
        if (body.values && typeof body.values === 'object') {
            held.values = Object.assign({}, body.values);
        }
    }

    function markConflict(name, localValue) {
        fields[name] = {
            state: CONFLICT,
            local: localValue,
            committed: held.values[name],
        };
        notify(name, localValue, fields[name]);
    }

    function notify(name, value, record) {
        listeners.slice().forEach(function (listener) {
            try {
                listener(name, value, record);
            } catch (err) {
                console.error('[Preferences] listener failed for ' + name, err);
            }
        });
    }

    function conflictBodyFrom(err) {
        if (!err || typeof err !== 'object') return null;
        const candidates = [err.detail, err.body && err.body.detail, err.data && err.data.detail];
        for (let i = 0; i < candidates.length; i += 1) {
            const candidate = candidates[i];
            if (candidate && typeof candidate === 'object'
                && candidate.status === 'stale_revision') {
                return candidate;
            }
        }
        return null;
    }

    const api = {
        NOT_HYDRATED: NOT_HYDRATED,
        HYDRATED: HYDRATED,
        READ_FAILED: READ_FAILED,
        COMMITTED: COMMITTED,
        PENDING: PENDING,
        FAILED: FAILED,
        CONFLICT: CONFLICT,
        clientId: clientId,
        get: get,
        committedValue: committedValue,
        stateFor: stateFor,
        status: status,
        revision: revision,
        hydrate: hydrate,
        set: set,
        setMany: setMany,
        applyRemote: applyRemote,
        retry: retry,
        discardLocal: discardLocal,
        adopt: adoptServerState,
        subscribe: subscribe,
        reset: reset,
    };

    globalThis.Preferences = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    console.log('[Preferences Module] Loaded');
})();
