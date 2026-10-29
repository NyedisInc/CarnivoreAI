/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { beforeAll, describe, expect, test } from 'vitest';
import '../plugins/builtin';
import { sessionCardMenuItems } from '../plugins/session-card-actions';
import { loadLegacyDrawer, type LegacyWindow } from '../sidebar-shell/legacy-fixture';
import { PLUGIN_CASE_NAMES, ROW_CASES, type RowCase, type RowCtx } from './golden-cases';
import { goldenOfNodes, type GoldenEntry } from './golden-normalize';
import './menus/all';
import { itemMenu } from './registry';
import type { RowMenuCtx } from './row-context';

const GOLDEN = path.join(__dirname, '__goldens__', 'row-menus.json');

let w: LegacyWindow;

beforeAll(() => {
    w = loadLegacyDrawer();
    w.CloudeWeb = { ...(w.CloudeWeb ?? {}), sessionCardMenuItems, autoSleep: { isKeptAwake: (name: string) => name === 'carnivore_kept' } };
});

function capturedPlugins(ctx: RowCtx): string {
    return sessionCardMenuItems(
        { name: String(ctx.name), unread: !!ctx.unread, hostKey: String(ctx.hostKey), sessionUuid: String(ctx.sessionUuid) || null, sessionId: (ctx.sessionId as string) ?? null, projectId: (ctx.projectId as number) ?? null },
        { flags: { show_mark_unread_control: true }, refresh: () => {} },
    ).map((i) => i.id).join(',');
}

function recordAll(menuOf: (c: RowCase, ctx: RowCtx) => GoldenEntry[]): Record<string, GoldenEntry[]> {
    const out: Record<string, GoldenEntry[]> = {};
    for (const c of ROW_CASES) {
        out[c.name] = menuOf(c, c.ctx);
        if (PLUGIN_CASE_NAMES.includes(c.name)) out[`${c.name} with plugins`] = menuOf(c, { ...c.ctx, pluginItems: capturedPlugins(c.ctx) });
    }
    return out;
}

function modelMenu(c: RowCase, ctx: RowCtx): GoldenEntry[] {
    const built = itemMenu(c.type, ctx as unknown as RowMenuCtx, { close: () => {}, glyph: () => '' });
    return built ? goldenOfNodes(built.nodes, true) : [];
}

describe('the row menus golden', () => {
    test('every row type in every representative state offers exactly the recorded menu, through the model', () => {
        void w;
        const now = recordAll(modelMenu);
        const golden = JSON.parse(fs.readFileSync(GOLDEN, 'utf8')) as Record<string, GoldenEntry[]>;
        expect(Object.keys(now)).toEqual(Object.keys(golden));
        for (const name of Object.keys(golden)) expect(now[name], name).toEqual(golden[name]);
    });
});
