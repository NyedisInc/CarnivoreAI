import type { Plugin } from 'vite';

const POPUP_LINK = /[ \t]*<link[^>]*popup-focus\.css[^>]*>\n?/;

export function popupFocusLast(): Plugin {
    return {
        name: 'widget-harness-popup-focus-last',
        transformIndexHtml: {
            order: 'post',
            handler(html: string): string {
                const found = POPUP_LINK.exec(html);
                if (!found) throw new Error('widget harness index.html does not link client/css/popup-focus.css');
                let out = html.replace(found[0], '').replace('</head>', `${found[0].trimEnd()}\n</head>`);
                if (!out.includes('/static/js/i18n/boot.js')) {
                    out = out.replace('</body>', '    <script type="module" src="/static/js/i18n/boot.js"></script>\n</body>');
                    out = out.replace(
                        /(<script type="module"[^>]*src="[^"]*widget-(?:lab|harness)[^"]*"[^>]*><\/script>)/,
                        '<script type="module" src="/static/js/i18n/boot.js"></script>\n    $1',
                    );
                    const first = out.indexOf('/static/js/i18n/boot.js');
                    const last = out.lastIndexOf('/static/js/i18n/boot.js');
                    if (first !== last) {
                        out = out.replace('    <script type="module" src="/static/js/i18n/boot.js"></script>\n</body>', '</body>');
                    }
                }
                return out;
            },
        },
    };
}
