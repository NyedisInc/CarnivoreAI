
console.log('[CloudeTerminal Module] Loading...');

(function (global) {
    'use strict';

    var PRIMARY_INPUT_OWNER = 'terminal:@primary';

    function openTerminalLink(_event, uri) {
        var url;
        try { url = new URL(uri); } catch (err) { return; }
        if (url.protocol !== 'https:' && url.protocol !== 'http:') return;
        var a = document.createElement('a');
        a.href = url.href;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        a.remove();
    }

    var SCROLLBACK_ROWS = 5000;

    var XTERM_OPTIONS = Object.freeze({
        linkHandler: Object.freeze({ activate: openTerminalLink }),
        cursorBlink: true,
        fontSize: 14,
        fontFamily: 'ui-monospace, "SF Mono", SFMono-Regular, Menlo, Monaco, "Cascadia Mono", "Roboto Mono", "Courier New", monospace',
        fontWeight: 'normal',
        fontWeightBold: 'bold',
        allowTransparency: true,
        allowProposedApi: true,
        convertEol: false,
        scrollback: SCROLLBACK_ROWS,
        scrollOnUserInput: false,
        windowsMode: false
    });

    var PAGE_CHROME_IDS = {
        detachSessionBtn: 'detachSessionBtn',
        statusText: 'statusText',
        fileInput: 'cloude-image-attach-input'
    };

    function readPageChrome(doc) {
        var d = doc || (typeof document !== 'undefined' ? document : null);
        var record = {};
        Object.keys(PAGE_CHROME_IDS).forEach(function (key) {
            var id = PAGE_CHROME_IDS[key];
            record[key] = function () {
                if (!d || typeof d.getElementById !== 'function') return null;
                return d.getElementById(id);
            };
        });
        return record;
    }

    function createTerminalClient(container, options) {
        var opts = options || {};
        if (typeof TerminalClientClass !== 'function') {
            throw new Error(
                'CloudeTerminal: no terminal class registered, so '
                + 'terminal.js did not load before this call');
        }
        return new TerminalClientClass({
            container: container || null,
            chrome: opts.chrome || readPageChrome(opts.document),
            wiring: opts.wiring || {},
            sessionId: opts.sessionId || null,
            role: opts.role || null,
            inputOwner: opts.inputOwner || null,
            xtermOptions: XTERM_OPTIONS
        });
    }

    /** @type {?function} terminal.js's Terminal class, once registered. */
    var TerminalClientClass = null;

    function register(cls) {
        if (typeof cls !== 'function') {
            throw new Error('CloudeTerminal: register() needs the Terminal class');
        }
        TerminalClientClass = cls;
    }

    global.CloudeTerminal = {
        createTerminalClient: createTerminalClient,
        readPageChrome: readPageChrome,
        register: register,
        PAGE_CHROME_IDS: PAGE_CHROME_IDS,
        PRIMARY_INPUT_OWNER: PRIMARY_INPUT_OWNER,
        XTERM_OPTIONS: XTERM_OPTIONS,
        SCROLLBACK_ROWS: SCROLLBACK_ROWS
    };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[CloudeTerminal Module] Exported as window.CloudeTerminal');
