import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { sessionSummaryLabel } from '../../../../client/js/labels/session-summary.js';
import { glyphSvg } from '../../../../client/js/icons/glyphs.js';
import { iconSvg } from '../../../../client/js/icons/icon-registry.js';
import { assignMenuKeys } from '../../../../client/js/menu-keys.js';
import { publishDrawer } from '../drawer/boot';
import { repaint } from '../drawer/paint';
import * as GroupStore from '../drawer/group-store';
import * as Identity from '../drawer/row-identity';
import * as Search from '../drawer/search';
import * as Store from '../drawer/store';
import { unmountPanel } from '../mount';
import { rowMenuBridge } from '../item-menu/row-bridge';

export function resetDrawer(): void {
    localStorage.clear();
    Store.load();
    GroupStore.reset();
    Identity.reset();
    Search.setQuery('');
}

export function drawList(rows: Record<string, unknown>[], extra: Record<string, unknown> = {}): string {
    let el = document.getElementById('session-sidebar-list');
    if (!el) {
        el = document.createElement('div');
        el.id = 'session-sidebar-list';
        el.className = 'session-sidebar-list';
        document.body.appendChild(el);
    }
    unmountPanel(el.id);
    paintDrawer({ listEl: el, _rows: rows, _listing: { ok: true }, _dragging: false, _missing: [], ...extra });
    return el.innerHTML.replace(/<!--[^>]*-->/g, '');
}

export function paintDrawer(ctrl: Record<string, any>): boolean {
    ctrl._missing = ctrl._missing || [];
    ctrl._listing = ctrl._listing || { ok: true };
    return repaint(ctrl as Parameters<typeof repaint>[0]);
}

/** Repo root, four levels up from web/src/lib/sidebar-shell. */
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

export const LEGACY_SCRIPTS: readonly string[] = [
    'i18n/tr.js',
    'kebab-icon.js', 'session-label.js', 'status-led.js', 'session-transport.js',
    'session-status-summary.js', 'ui-flags.js', 'session-status-ui.js',
    'session-row-actions-confirm.js', 'session-row-actions.js',
    'session-theme-tint.js',
    'effort-level.js', 'session-model-icon.js', 'agent-family-icon.js',
    'session-row-menu-icons.js',
];

export type LegacyWindow = Record<string, any>;

export function loadLegacyDrawer(): LegacyWindow {
    const g = globalThis as LegacyWindow;
    if (g.__legacyDrawerLoaded) return g;
    g.CloudeI18n = createI18n();
    g.CloudeGlyphs = { glyphSvg, iconSvg };
    g.CloudeMenuKeys = { assignMenuKeys };
    g.CloudeLabels = { sessionSummaryLabel };
    publishDrawer(g, null);
    g.CloudeWeb = { ...(g.CloudeWeb ?? {}), rowMenu: rowMenuBridge };
    const log = console.log;
    console.log = () => {};
    try {
        for (const file of LEGACY_SCRIPTS) {
            const src = fs.readFileSync(path.join(repoRoot, 'client', 'js', file), 'utf8');
            new Function(src)();
        }
    } finally {
        console.log = log;
    }
    g.__legacyDrawerLoaded = true;
    return g;
}

export function canonicalDom(el: Node): string {
    const out: string[] = [];
    const walk = (node: Node): void => {
        for (const child of Array.from(node.childNodes)) {
            if (child.nodeType === 8) continue;
            if (child.nodeType === 3 && child.textContent === '') continue;
            if (child.nodeType === 3) {
                out.push(JSON.stringify(child.textContent));
                continue;
            }
            if (child.nodeType !== 1) continue;
            const e = child as Element;
            const attrs = Array.from(e.attributes)
                .map((a) => `${a.name}=${JSON.stringify(a.value)}`)
                .sort();
            out.push(`<${e.tagName.toLowerCase()} ${attrs.join(' ')}>`);
            walk(e);
            out.push(`</${e.tagName.toLowerCase()}>`);
        }
    };
    walk(el);
    return out.join('\n');
}
