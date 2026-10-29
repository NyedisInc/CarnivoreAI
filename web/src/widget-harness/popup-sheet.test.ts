import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const ROOT = new URL('../../../', import.meta.url);
const read = (path: string): string => readFileSync(new URL(path, ROOT), 'utf8');

export function stylesheets(html: string): string[] {
  const bare = html.replace(/<!--[\s\S]*?-->/g, '');
  return [...bare.matchAll(/<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"/g)].map((match) => match[1]!);
}

const POPUP = '/static/css/popup-focus.css';

describe('the harness page loads the one popup look last, as the live app does', () => {
  const harness = stylesheets(read('web/src/widget-harness/index.html'));
  const app = stylesheets(read('client/index.html'));

  it('the live app ends on popup-focus.css', () => {
    expect(app.at(-1)).toBe(POPUP);
  });

  it('the harness page ends on popup-focus.css too', () => {
    expect(harness).toContain(POPUP);
    expect(harness.at(-1)).toBe(POPUP);
  });

  it('can go red: a page without the sheet, or with a sheet after it, is read as wrong', () => {
    expect(stylesheets('<link rel="stylesheet" href="/static/css/a.css"><link rel="stylesheet" href="/static/css/b.css">').at(-1)).not.toBe(POPUP);
    expect(stylesheets(`<link rel="stylesheet" href="${POPUP}"><link rel="stylesheet" href="/static/css/late.css">`).at(-1)).not.toBe(POPUP);
    expect(stylesheets(`<!-- <link rel="stylesheet" href="${POPUP}"> -->`)).toEqual([]);
  });
});
