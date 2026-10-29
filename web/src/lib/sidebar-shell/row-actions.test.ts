/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { beforeAll, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer, type LegacyWindow } from './legacy-fixture';
import { rowMenuItems } from '../item-menu/menus/row';
import { contextFromTrigger } from '../item-menu/row-context';

let win: LegacyWindow;

beforeAll(() => {
    win = loadLegacyDrawer();
    resetDrawer();
});

it('sidebar rows paint the same control with the same wording', () => {
    const html = drawList([
        { name: 'cloude_alive', created_by_cloude: true, status: 'idle', is_active: true, project_id: null },
        { name: 'cloude_gone', created_by_cloude: true, status: 'dead', is_active: false, project_id: null },
    ]);
    function offeredFor(name: string): { inline: string[]; menu: string[]; all: string[] } {
        const rowRe = new RegExp(`<[^>]*data-name="${name}"[\\s\\S]*?(?=<div[^>]*data-name="|$)`);
        const seg = (html.match(rowRe) || [''])[0];
        const inline = [...seg.matchAll(/data-session-action="([^"]+)"/g)].map((m) => m[1] as string);
        const tag = (seg.match(/<button[^>]*data-row-menu="[^"]*"[^>]*>/) || [])[0];
        let menu: string[] = [];
        if (tag) {
            const stub = {
                getAttribute(a: string) {
                    const m = tag.match(new RegExp(`\\s${a}="([^"]*)"`));
                    return m ? m[1] : null;
                },
            };
            menu = rowMenuItems(contextFromTrigger(stub as unknown as Element)!).map((i) => i.id);
        }
        return { inline, menu, all: [...inline, ...menu] };
    }

    const alive = offeredFor('cloude_alive');
    const gone = offeredFor('cloude_gone');

    assert.ok(html.includes('data-row-menu='), 'a live row must paint a menu trigger to hang its actions off');
    assert.ok(alive.all.includes('close'), 'a live row offers close');
    assert.ok(gone.all.includes('remove'), 'a dead row offers remove');
    assert.ok(!alive.all.includes('remove'), 'and never both on one row');
    assert.ok(!gone.all.includes('close'));
    assert.ok(alive.menu.includes('restart'), 'a LIVE row must offer restart, in its menu');
    assert.ok(gone.inline.includes('restart'), 'a DEAD row must offer restart, inline');
});
