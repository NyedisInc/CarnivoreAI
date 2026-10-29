
console.log('[TerminalSearchEngine Module] Loading...');

(function () {
    'use strict';

    function create() {

    var HIGHLIGHT_LIMIT = 1000;

    var DECORATION_COLOURS = [
        { option: 'matchBackground', prop: '--terminal-search-match-bg', fallback: '#4d3b30' },
        { option: 'matchBorder', prop: '--terminal-search-match-border', fallback: '#8a5a44' },
        { option: 'matchOverviewRuler', prop: '--terminal-search-match-ruler', fallback: '#8a5a44' },
        { option: 'activeMatchBackground', prop: '--terminal-search-active-bg', fallback: '#d77757' },
        { option: 'activeMatchBorder', prop: '--terminal-search-active-border', fallback: '#e88768' },
        { option: 'activeMatchColorOverviewRuler', prop: '--terminal-search-active-ruler', fallback: '#d77757' }
    ];

    var HEX_COLOUR = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

    var addons = new WeakMap();

    var resultListeners = [];

    var activeTerm = null;

    var lastQuery = '';
    var lastOptions = null;

    var warnedMissing = false;

    function addonClass() {
        var ns = (typeof window !== 'undefined') ? window.SearchAddon : null;
        return (ns && typeof ns.SearchAddon === 'function') ? ns.SearchAddon : null;
    }

    function available() {
        if (addonClass()) return true;
        if (!warnedMissing) {
            warnedMissing = true;
            console.warn('TerminalSearchEngine: xterm-addon-search did not load; '
                + 'search is a no-op. Check the /static/vendor/xterm/ script tag.');
        }
        return false;
    }

    function themedColour(prop, fallback) {
        try {
            var host = activeTerm && activeTerm.element
                ? activeTerm.element.parentElement : document.querySelector('.terminal-container');
            if (!host || typeof window.getComputedStyle !== 'function') return fallback;
            var value = window.getComputedStyle(host).getPropertyValue(prop);
            value = (value || '').trim();
            return HEX_COLOUR.test(value) ? value : fallback;
        } catch (err) {
            console.warn('TerminalSearchEngine: could not read ' + prop, err);
            return fallback;
        }
    }

    function decorations() {
        var out = {};
        DECORATION_COLOURS.forEach(function (c) {
            out[c.option] = themedColour(c.prop, c.fallback);
        });
        return out;
    }

    function attach(term) {
        if (!term) return null;
        activeTerm = term;
        if (addons.has(term)) return addons.get(term);
        if (!available()) return null;

        var Addon = addonClass();
        var addon;
        try {
            addon = new Addon({ highlightLimit: HIGHLIGHT_LIMIT });
            term.loadAddon(addon);
        } catch (err) {
            console.warn('TerminalSearchEngine: loadAddon failed', err);
            return null;
        }
        if (addon.onDidChangeResults) {
            addon.onDidChangeResults(function (r) {
                emit(r);
            });
        }
        addons.set(term, addon);
        return addon;
    }

    function current() {
        return (activeTerm && addons.has(activeTerm)) ? addons.get(activeTerm) : null;
    }

    function emit(r) {
        var count = (r && typeof r.resultCount === 'number' && r.resultCount >= 0)
            ? r.resultCount : null;
        var index = (r && typeof r.resultIndex === 'number' && r.resultIndex >= 0)
            ? r.resultIndex : null;
        var payload = { resultIndex: index, resultCount: count, limit: HIGHLIGHT_LIMIT };
        resultListeners.slice().forEach(function (fn) {
            try {
                fn(payload);
            } catch (err) {
                console.warn('TerminalSearchEngine: a results listener threw', err);
            }
        });
    }

    function onResults(cb) {
        if (typeof cb !== 'function') return function () {};
        resultListeners.push(cb);
        return function () {
            var i = resultListeners.indexOf(cb);
            if (i !== -1) resultListeners.splice(i, 1);
        };
    }

    function searchOptions(opts) {
        var o = opts || {};
        return {
            regex: !!o.regex,
            caseSensitive: !!o.caseSensitive,
            wholeWord: false,
            incremental: o.incremental !== false,
            decorations: decorations()
        };
    }

    function find(q, opts, dir) {
        lastQuery = q || '';
        lastOptions = opts || null;
        if (!lastQuery) {
            clear();
            return false;
        }
        var addon = current() || attach(activeTerm);
        if (!addon) return false;
        try {
            return dir === 'prev'
                ? !!addon.findPrevious(lastQuery, searchOptions(opts))
                : !!addon.findNext(lastQuery, searchOptions(opts));
        } catch (err) {
            console.warn('TerminalSearchEngine: find failed', err);
            return false;
        }
    }

    /* already running */
    function next() {
        var o = Object.assign({}, lastOptions || {}, { incremental: false });
        return find(lastQuery, o, 'next');
    }

    function prev() {
        var o = Object.assign({}, lastOptions || {}, { incremental: false });
        return find(lastQuery, o, 'prev');
    }

    function clear() {
        lastQuery = '';
        var addon = current();
        if (addon && typeof addon.clearDecorations === 'function') {
            try {
                addon.clearDecorations();
            } catch (err) {
                console.warn('TerminalSearchEngine: clearDecorations failed', err);
            }
        }
        emit({ resultIndex: -1, resultCount: 0 });
    }

    function predicate(q, opts) {
        var o = opts || {};
        var query = q || '';
        if (!query) return function () { return true; };

        if (o.regex) {
            var re;
            try {
                re = new RegExp(query, o.caseSensitive ? '' : 'i');
            } catch (err) {
                return function () { return false; };
            }
            return function (text) {
                re.lastIndex = 0;
                return re.test(String(text == null ? '' : text));
            };
        }

        if (o.caseSensitive) {
            return function (text) {
                return String(text == null ? '' : text).indexOf(query) !== -1;
            };
        }
        var needle = query.toLowerCase();
        return function (text) {
            return String(text == null ? '' : text).toLowerCase().indexOf(needle) !== -1;
        };
    }

    return {
        attach: attach,
        find: find,
        next: next,
        prev: prev,
        clear: clear,
        onResults: onResults,
        predicate: predicate,
        HIGHLIGHT_LIMIT: HIGHLIGHT_LIMIT
    };
    }

    window.TerminalSearchEngine = Object.assign({ create: create }, create());
})();

console.log('[TerminalSearchEngine Module] Exported as window.TerminalSearchEngine');
