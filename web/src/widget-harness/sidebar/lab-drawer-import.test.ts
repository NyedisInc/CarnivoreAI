// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { DRAWER_MODULES, DRAWER_ROOT_IDS, DRAWER_SCRIPTS, parseDrawerMarkup, sheetPath } from './lab-drawer-import';
import { DEFAULT_SIDEBAR_VIEW, viewFromQuery, viewToQuery, widthPx } from './sidebar-state';

const PAGE = readFileSync(resolve(__dirname, '../../../../client/index.html'), 'utf8');

function idsIn(html: string): string[] {
  return [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]!).sort();
}

describe('the real drawer is imported from client/index.html, not copied', () => {
  const markup = parseDrawerMarkup(PAGE);

  it('adopts every drawer root the page carries', () => {
    expect(Object.keys(markup.roots).sort()).toEqual([...DRAWER_ROOT_IDS].sort());
  });

  it('the frame drawer id set equals the ids inside the page roots', () => {
    const fromRoots = Object.values(markup.roots).flatMap((html) => idsIn(html)).sort();
    expect(markup.ids).toEqual(fromRoots);
    expect(markup.ids).toContain('session-sidebar-panel');
    expect(markup.ids).toContain('session-sidebar-rail');
  });

  it('every render-helper script and module the drawer reads is still listed by the page, in its order', () => {
    for (const name of DRAWER_SCRIPTS) expect(markup.scripts.some((src) => src.endsWith(`/${name}.js`)), name).toBe(true);
    for (const name of DRAWER_MODULES) expect(markup.modules.some((src) => src.endsWith(`/${name}.js`)), name).toBe(true);
  });

  it('keeps the page stylesheets, drops the app bundle own, and strips the cache query', () => {
    expect(markup.sheets.length).toBeGreaterThan(0);
    expect(markup.sheets.every((href) => !href.includes('?'))).toBe(true);
    expect(markup.sheets).not.toContain('/static/dist/app.css');
    expect(sheetPath('/static/css/styles.css?v=ab12')).toBe('/static/css/styles.css');
    expect(sheetPath('https://elsewhere.test/x.css')).toBeNull();
  });

  it('is negative-controlled: a page without the drawer is refused loudly', () => {
    expect(() => parseDrawerMarkup('<html><body><p>nothing</p></body></html>')).toThrow(/session-sidebar-panel/);
  });
});

describe('sidebar state', () => {
  it('round-trips a view through the query', () => {
    const view = { width: 'wide', folded: true, area: 'glance', density: 'detailed' } as const;
    expect(viewFromQuery(new URLSearchParams(viewToQuery(view)))).toEqual(view);
    expect(viewFromQuery(new URLSearchParams())).toEqual(DEFAULT_SIDEBAR_VIEW);
  });

  it('snaps widths inside the limits, narrowest to widest', () => {
    const limits = { min: 220, normal: 320, max: 560 };
    expect(widthPx('min', limits)).toBe(220);
    expect(widthPx('default', limits)).toBe(320);
    expect(widthPx('max', limits)).toBe(560);
    expect(widthPx('wide', limits)).toBeGreaterThan(320);
    expect(widthPx('wide', limits)).toBeLessThan(560);
  });
});
