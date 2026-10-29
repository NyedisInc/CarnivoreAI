
console.log('[SlashCommandsBoot Module] Loading...');

(function (global) {
    'use strict';

    /** @type {string|null} The directory the loaded palette belongs to. */
    var loadedFor = null;

    /** @type {string|null} The directory an in-flight fetch is for. */
    var loadingFor = null;

    /** @type {Promise|null} The in-flight fetch, so a second call can join. */
    var inFlight = null;

    function insert(command, ticket) {
        if (global.TerminalController) {
            global.TerminalController.insertText(command, ticket);
        }
    }

    function start(workingDir) {
        var modal = global.SlashCommandsModal;
        if (!modal) return;
        var dir = workingDir || null;

        if (modal.loaded && loadedFor === dir) {
            return;
        }

        // already running
        if (inFlight && loadingFor === dir) {
            return;
        }

        loadingFor = dir;
        var started;
        try {
            started = Promise.resolve(modal.init(insert, dir));
        } catch (err) {
            loadingFor = null;
            console.warn('[slash-commands] palette could not be started', err);
            return;
        }
        inFlight = started
            .then(function () {
                loadedFor = dir;
            })
            .catch(function (err) {
                loadedFor = null;
                console.warn('[slash-commands] palette unavailable for now', err);
            })
            .then(function () {
                inFlight = null;
                loadingFor = null;
            });
    }

    // could not

    function state() {
        return { loadedFor: loadedFor, loading: inFlight !== null };
    }

    global.SlashCommandsBoot = {
        start: start,
        state: state
    };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[SlashCommandsBoot Module] Exported as window.SlashCommandsBoot');
