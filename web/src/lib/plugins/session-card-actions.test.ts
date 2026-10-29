import { afterEach, describe, expect, test, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

import './builtin';
import { runSessionCardAction, sessionCardMenuItems } from './session-card-actions';
import { surfacesOf } from './registry';
import { ACTION_ID, FLAG, unreadCplug } from '../../cplugs/unread';
import type { PluginContext, SessionCardRow } from './types';

const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

interface RecordingContext extends PluginContext {
    refresh: ReturnType<typeof vi.fn<() => void>>;
}

function ctx(flags: Record<string, boolean> = {}): RecordingContext {
    return { flags, refresh: vi.fn<() => void>() };
}

function row(overrides: Partial<SessionCardRow> = {}): SessionCardRow {
    return { name: 'cloude_api', unread: false, ...overrides };
}

function legacyMarkUnreadHtml(): (name: string, unread: boolean) => string {
    const context: Record<string, unknown> = { console, window: {} };
    vm.createContext(context);
    const src = fs.readFileSync(
        path.join(repoRoot, 'client', 'js', 'session-status-ui.js'), 'utf8');
    vm.runInContext(src, context);
    const ui = (context['window'] as Record<string, unknown>)['SessionStatusUI'] as {
        markUnreadHtml(name: string, unread: boolean): string;
    };
    return (name, unread) => ui.markUnreadHtml(name, unread);
}

interface Parsed {
    tag: string;
    attrs: Record<string, string>;
    inner: string;
}

function parse(html: string): Parsed {
    const open = html.match(/^<([a-z]+)((?:\s+[a-zA-Z-]+="[^"]*")*)\s*>/);
    if (!open) throw new Error(`not a single open tag: ${html.slice(0, 80)}`);
    const close = `</${open[1]}>`;
    if (!html.endsWith(close)) throw new Error(`does not end with ${close}`);
    const attrs: Record<string, string> = {};
    for (const m of (open[2] ?? '').matchAll(/\s+([a-zA-Z-]+)="([^"]*)"/g)) {
        attrs[m[1] as string] = m[2] as string;
    }
    return {
        tag: open[1] as string,
        attrs,
        inner: html.slice(open[0].length, html.length - close.length),
    };
}

function pluginLabel(r: SessionCardRow): string {
    const contribution = unreadCplug.plugins![0]!;
    return (contribution.payload as { label(row: SessionCardRow): string }).label(r);
}

afterEach(() => {
    delete (globalThis as { API?: unknown }).API;
});

describe('the shipped surface', () => {
    test('mark-unread is registered on session-card-action, exactly once', () => {
        const held = surfacesOf('session-card-action');
        expect(held.map((c) => c.id)).toContain(ACTION_ID);
        expect(held.filter((c) => c.id === ACTION_ID)).toHaveLength(1);
    });

    test('it contributes to no other surface', () => {
        expect(surfacesOf('sidebar-item')).toEqual([]);
        expect(surfacesOf('launchpad-panel')).toEqual([]);
        expect(surfacesOf('status-source')).toEqual([]);
    });
});

describe('the flag gates it, both ways', () => {
    test('flag absent - the control is rendered, because a failed read never hides', () => {
        const rendered = sessionCardMenuItems(row(), ctx({}));
        expect(rendered.map((a) => a.id)).toContain(ACTION_ID);
    });

    test('flag true - the control is rendered', () => {
        expect(sessionCardMenuItems(row(), ctx({ [FLAG]: true })).map((a) => a.id))
            .toContain(ACTION_ID);
    });

    test('NEGATIVE CONTROL: flag false - the control is ABSENT', () => {
        const rendered = sessionCardMenuItems(row(), ctx({ [FLAG]: false }));
        expect(rendered.map((a) => a.id)).not.toContain(ACTION_ID);
        expect(JSON.stringify(rendered)).not.toContain('unread');
    });

    test('NEGATIVE CONTROL: this file would notice if enabled were ignored', () => {
        const on = sessionCardMenuItems(row(), ctx({ [FLAG]: true }));
        const off = sessionCardMenuItems(row(), ctx({ [FLAG]: false }));
        expect(on.map((a) => a.id)).toContain(ACTION_ID);
        expect(off.map((a) => a.id)).not.toContain(ACTION_ID);
        expect(off).toHaveLength(on.length - 1);
        expect(off).not.toEqual(on);
    });

    test('a disabled action cannot be RUN either, even from a stale fragment', () => {
        const setSessionUnread = vi.fn(async () => ({}));
        (globalThis as { API?: unknown }).API = { setSessionUnread };
        const context = ctx({ [FLAG]: false });
        return runSessionCardAction(ACTION_ID, row(), context).then((ran) => {
            expect(ran).toBe(false);
            expect(setSessionUnread).not.toHaveBeenCalled();
        });
    });
});

describe('equivalence with the legacy control', () => {
    const legacy = legacyMarkUnreadHtml();

    function legacyLabel(r: SessionCardRow): string {
        const p = parse(legacy(r.name, r.unread));
        expect(p.attrs['title']).toBe(p.attrs['aria-label']);
        return p.attrs['title'] as string;
    }

    for (const unread of [false, true]) {
        test(`unread=${unread}: the two surfaces say the same words`, () => {
            const r = row({ unread });
            expect(pluginLabel(r)).toBe(legacyLabel(r));
        });
    }

    test('the label states the RESULT, so it flips with the row', () => {
        expect(pluginLabel(row({ unread: false }))).toMatch(/mark unread/);
        expect(pluginLabel(row({ unread: true }))).toMatch(/clear unread/);
    });

    test('NEGATIVE CONTROL: the comparison can actually fail', () => {
        expect(pluginLabel(row({ unread: true })))
            .not.toBe(legacyLabel(row({ unread: false })));
    });

    test('NEGATIVE CONTROL: the parser refuses markup it cannot read', () => {
        expect(() => parse('')).toThrow();
        expect(() => parse('<span class=unquoted>x</span>')).toThrow();
        expect(() => parse('<span>x')).toThrow();
    });

    test('the shortcut letter does not collide with the native menu table', () => {
        const native = new Set(['R', 'G', 'F', 'N', 'M', 'T', 'C']);
        const items = sessionCardMenuItems(row(), ctx({}));
        expect(items.length).toBeGreaterThan(0);
        for (const item of items) expect(native.has(item.shortcut)).toBe(false);
        const letters = items.map((item) => item.shortcut);
        expect(new Set(letters).size).toBe(letters.length);
    });

    test('the order lands in a gap the native table left, not on top of one', () => {
        const taken = new Set([100, 300, 400, 500, 600, 700, 800]);
        for (const item of sessionCardMenuItems(row(), ctx({}))) {
            expect(taken.has(item.order)).toBe(false);
            expect(item.order).toBeGreaterThan(100);
            expect(item.order).toBeLessThan(300);
        }
    });
});

describe('running it', () => {
    test('it PATCHes the opposite of the painted state, then repaints', async () => {
        const setSessionUnread = vi.fn(async () => ({}));
        (globalThis as { API?: unknown }).API = { setSessionUnread };
        const context = ctx({});
        const ran = await runSessionCardAction(ACTION_ID, row({ unread: false }), context);
        expect(ran).toBe(true);
        expect(setSessionUnread).toHaveBeenCalledWith('cloude_api', true);
        expect(context.refresh).toHaveBeenCalledTimes(1);
    });

    test('an already-unread row is cleared', async () => {
        const setSessionUnread = vi.fn(async () => ({}));
        (globalThis as { API?: unknown }).API = { setSessionUnread };
        await runSessionCardAction(ACTION_ID, row({ unread: true }), ctx({}));
        expect(setSessionUnread).toHaveBeenCalledWith('cloude_api', false);
    });

    test('a failed PATCH is logged, swallowed, and does NOT repaint', async () => {
        const setSessionUnread = vi.fn(async () => { throw new Error('boom'); });
        (globalThis as { API?: unknown }).API = { setSessionUnread };
        const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
        const context = ctx({});
        try {
            await expect(runSessionCardAction(ACTION_ID, row(), context)).resolves.toBe(true);
            expect(spy).toHaveBeenCalled();
        } finally {
            spy.mockRestore();
        }
        expect(context.refresh).not.toHaveBeenCalled();
    });

    test('an unknown id runs nothing and says so', async () => {
        const setSessionUnread = vi.fn(async () => ({}));
        (globalThis as { API?: unknown }).API = { setSessionUnread };
        expect(await runSessionCardAction('no-such-action', row(), ctx({}))).toBe(false);
        expect(setSessionUnread).not.toHaveBeenCalled();
    });

    test('a missing window.API is reported, not thrown past the menu', async () => {
        const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
        const context = ctx({});
        try {
            expect(await runSessionCardAction(ACTION_ID, row(), context)).toBe(true);
            expect(spy).toHaveBeenCalled();
        } finally {
            spy.mockRestore();
        }
        expect(context.refresh).not.toHaveBeenCalled();
    });
});

describe('a session on a paired Mac (issue #163, P8b)', () => {
  const context = { flags: {}, refresh: () => {} } as never;
  const ids = (hostKey: string | null) =>
    sessionCardMenuItems({ name: 'x', unread: false, hostKey }, context).map((i) => i.id);

  test('the share read only control is hidden and never runs for a peer session, and stays for a local one', async () => {
    expect(ids('local')).toContain('share-read-only');
    expect(ids(null)).toContain('share-read-only');
    expect(ids('peer-studio')).not.toContain('share-read-only');
    expect(ids('peer-studio')).toContain('mark-unread');
    expect(await runSessionCardAction('share-read-only', { name: 'x', unread: false, hostKey: 'peer-studio' }, context)).toBe(false);
  });
});
