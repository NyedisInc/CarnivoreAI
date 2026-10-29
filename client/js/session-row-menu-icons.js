
console.log('[SessionRowMenuIcons Module] Loading...');

(function () {
    'use strict';

    var DEFAULT_SIZE = 14;

    var LOOP =
        '<path d="M3 8a5 5 0 0 1 8.5-3.5L13 6" stroke="currentColor" '
        + 'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>'
        + '<path d="M13 3v3h-3" stroke="currentColor" stroke-width="1.3" '
        + 'stroke-linecap="round" stroke-linejoin="round"/>'
        + '<path d="M13 8a5 5 0 0 1-8.5 3.5L3 10" stroke="currentColor" '
        + 'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>'
        + '<path d="M3 13v-3h3" stroke="currentColor" stroke-width="1.3" '
        + 'stroke-linecap="round" stroke-linejoin="round"/>';

    var GLYPHS = {
        schedule:
            '<circle cx="8" cy="8" r="5.6" stroke="currentColor" stroke-width="1.3"/>'
            + '<path d="M8 4.8V8l2.2 1.4" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linecap="round" stroke-linejoin="round"/>',
        rename:
            '<path d="M11.15 2.15a1.2 1.2 0 0 1 1.7 0l1 1a1.2 1.2 0 0 1 0 1.7'
            + 'l-7.4 7.4-3.2.8.8-3.2z" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linejoin="round" stroke-linecap="round"/>'
            + '<path d="M9.7 3.6l2.7 2.7" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linecap="round"/>',
        'mark-unread':
            '<circle cx="8" cy="8" r="5.25" stroke="currentColor" stroke-width="1.3"/>'
            + '<circle cx="8" cy="8" r="2" fill="currentColor"/>',
        'mark-read':
            '<circle cx="8" cy="8" r="5.25" stroke="currentColor" stroke-width="1.3"/>',
        'move-to-group':
            '<path d="M2 4.5A1.25 1.25 0 0 1 3.25 3.25h3l1.25 1.5h5.25'
            + 'A1.25 1.25 0 0 1 14 6v6.25A1.25 1.25 0 0 1 12.75 13.5h-9.5'
            + 'A1.25 1.25 0 0 1 2 12.25z" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linejoin="round"/>',
        'remove-from-group':
            '<path d="M2 4.5A1.25 1.25 0 0 1 3.25 3.25h3l1.25 1.5h5.25'
            + 'A1.25 1.25 0 0 1 14 6v6.25A1.25 1.25 0 0 1 12.75 13.5h-9.5'
            + 'A1.25 1.25 0 0 1 2 12.25z" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linejoin="round"/>'
            + '<path d="M5.3 8.6h5.4" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linecap="round"/>',
        pin:
            '<path d="M8 11.5V15M3.5 11.5h9l-1.4-2.6V2.5H4.9v6.4z" stroke="currentColor" '
            + 'stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"/>',
        fork:
            '<circle cx="4" cy="3.25" r="1.5" stroke="currentColor" stroke-width="1.3"/>'
            + '<circle cx="4" cy="12.75" r="1.5" stroke="currentColor" stroke-width="1.3"/>'
            + '<circle cx="12" cy="6.25" r="1.5" stroke="currentColor" stroke-width="1.3"/>'
            + '<path d="M4 4.75v6.5" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linecap="round"/>'
            + '<path d="M4 8.5c0-1.8 1.4-2.75 3-2.75h3.6" stroke="currentColor" '
            + 'stroke-width="1.3" stroke-linecap="round"/>',
        'new-in-folder':
            '<path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.4" '
            + 'stroke-linecap="round"/>',
        'new-terminal-here':
            '<rect x="2" y="3" width="12" height="10" rx="1.2" stroke="currentColor" '
            + 'stroke-width="1.3"/>'
            + '<path d="M4.5 6l2.5 2-2.5 2M8.5 10h3" stroke="currentColor" '
            + 'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
        'show-path':
            '<path d="M8 14s4.25-3.9 4.25-7.25a4.25 4.25 0 0 0-8.5 0C3.75 10.1 8 14 8 14z" '
            + 'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>'
            + '<circle cx="8" cy="6.75" r="1.5" stroke="currentColor" stroke-width="1.3"/>',
        // conversation id
        'copy-session-id':
            '<rect x="5.5" y="5.5" width="8" height="8" rx="1.2" stroke="currentColor" stroke-width="1.3"/>'
            + '<path d="M10.5 3.5v-.3A.7.7 0 0 0 9.8 2.5H3.7a.7.7 0 0 0-.7.7v6.1a.7.7 0 0 0 .7.7h.3" '
            + 'stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>',
        crosstalk:
            '<path d="M2.5 3h7.5v5H5.5L3 10V8h-.5z" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linejoin="round"/>'
            + '<path d="M12 6h1.5v5H13v2l-2.5-2H7V9.5" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linejoin="round"/>',
        bookmark:
            '<path d="M4.25 2.25H11.75V13.75L8 10.75L4.25 13.75Z" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linejoin="round"/>',
        mute:
            '<path d="M4.5 10.5V7a3.5 3.5 0 0 1 7 0v3.5l1.2 1.8a.5.5 0 0 1-.4.7'
            + 'H3.7a.5.5 0 0 1-.4-.7z" stroke="currentColor" stroke-width="1.3" '
            + 'stroke-linejoin="round" stroke-linecap="round"/>'
            + '<path d="M6.5 13a1.5 1.5 0 0 0 3 0" stroke="currentColor" '
            + 'stroke-width="1.3" stroke-linecap="round"/>'
            + '<path d="M2.5 2.5l11 11" stroke="currentColor" stroke-width="1.4" '
            + 'stroke-linecap="round"/>',
        restart: LOOP,
        'update-restart': LOOP,
        'restart-now': LOOP,
        'reconnect-mcp':
            '<path d="M6 2v3M10 2v3M4.5 5h7v2.5a3.5 3.5 0 0 1-7 0zM8 11v3" stroke="currentColor" '
            + 'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
        'mcp-drop':
            '<path d="M8 2.8v6.4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
            + '<circle cx="8" cy="12.5" r="1.2" fill="currentColor"/>',
        close:
            '<path d="M8 2.3c-2.9 0-5 2-5 4.8 0 1.5.7 2.7 1.7 3.3v1.9h6.6v-1.9'
            + 'c1-.6 1.7-1.8 1.7-3.3 0-2.8-2.1-4.8-5-4.8z" stroke="currentColor" '
            + 'stroke-width="1.6" stroke-linejoin="round"/>'
            + '<circle cx="6.1" cy="7.3" r="1.1" fill="currentColor"/>'
            + '<circle cx="9.9" cy="7.3" r="1.1" fill="currentColor"/>'
            + '<path d="M6.7 12.3v1.4M9.3 12.3v1.4" stroke="currentColor" '
            + 'stroke-width="1.3" stroke-linecap="round"/>',
        sleep:
            '<path d="M13.3 9.3A6 6 0 0 1 6.7 2.7a6 6 0 1 0 6.6 6.6z" '
            + 'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>',
        wake:
            '<circle cx="8" cy="8" r="2.75" stroke="currentColor" stroke-width="1.3"/>'
            + '<path d="M8 1.5V3M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1.1 1.1'
            + 'M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" '
            + 'stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>',
        'move-up':
            '<path d="M8 13V3M4.5 6.5L8 3l3.5 3.5" stroke="currentColor" '
            + 'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
        'move-down':
            '<path d="M8 3v10M4.5 9.5L8 13l3.5-3.5" stroke="currentColor" '
            + 'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
        'send-to':
            '<g transform="scale(.6667)" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
            + '<path d="M4.2 22.0C4.25 21.5 4.2 20.02 4.5 19.0C4.8 17.98 5.33 16.87 6.0 15.9C6.67 14.93 7.71 14.03 8.5 13.2C9.29 12.37 10.38 11.31 10.75 10.93L7.21 10.85L11.71 7.85C11.84 7.71 12.05 7.29 12.47 7.01C12.89 6.73 13.55 6.64 14.23 6.2C14.91 5.76 15.69 5.1 16.53 4.38C17.38 3.66 18.84 2.3 19.3 1.88L20.27 2.22L17.42 7.74L21.62 5.9C21.59 6.22 21.89 7.06 21.46 7.84C21.03 8.62 19.65 9.7 19.03 10.58C18.41 11.46 17.97 12.69 17.76 13.11C17.92 13.56 18.46 14.85 18.7 15.8C18.94 16.75 19.17 17.77 19.2 18.8C19.23 19.83 18.95 21.47 18.9 22.0L4.2 22.0Z"/>'
            + '<circle cx="14.89" cy="8.19" r="0.75" fill="currentColor" stroke="none"/></g>',
        colour:
            '<path d="M8 2.2c2.4 3 4 5.1 4 7.1a4 4 0 0 1-8 0c0-2 1.6-4.1 4-7.1z" '
            + 'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>',
    };

    var SHARED = {
        'share-read-only': 'telescope',
        'save-blueprint': 'cube',
        'load-blueprint': 'cube',
        'group-icon': 'star',
        'lock-star': 'star',
        'keep-awake': 'coffee',
        'huddle-project-lead': 'star',
        'huddle-do-not-disturb': 'do-not-disturb',
        'move-to-folder': 'folder',
    };

    function svg(id, size) {
        var px = (typeof size === 'number' && size > 0) ? size : DEFAULT_SIZE;
        var borrowed = SHARED[id];
        if (borrowed) {
            var shared = globalThis.CloudeGlyphs;
            return (shared && typeof shared.glyphSvg === 'function')
                ? shared.glyphSvg(borrowed, px) : '';
        }
        if (id === 'agent') {
            var model = globalThis.SessionModelIcon;
            return (model && model.ROBOT)
                ? '<svg width="' + px + '" height="' + px + '" viewBox="0 0 20 20" '
                    + 'fill="none" aria-hidden="true">' + model.ROBOT + '</svg>'
                : '';
        }
        var inner = GLYPHS[id];
        if (!inner) return '';
        return (
            '<svg width="' + px + '" height="' + px + '" viewBox="0 0 16 16" '
            + 'fill="none" aria-hidden="true">' + inner + '</svg>'
        );
    }

    window.SessionRowMenuIcons = { svg: svg, DEFAULT_SIZE: DEFAULT_SIZE };
})();

console.log('[SessionRowMenuIcons Module] Exported as window.SessionRowMenuIcons');
