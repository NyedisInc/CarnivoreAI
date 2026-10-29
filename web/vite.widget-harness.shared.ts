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
                return html.replace(found[0], '').replace('</head>', `${found[0].trimEnd()}\n</head>`);
            },
        },
    };
}
