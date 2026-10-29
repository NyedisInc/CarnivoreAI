/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { glyphSvg } from '../../../../client/js/icons/glyphs.js';
import { browserRunningHost } from './running-host';

/* the whole suite */
const repoRoot = path.join(process.cwd(), '..');

/** The globals this file hangs on `window` and must take back off it. */
const INSTALLED = [
    'SessionRowActions', 'SessionStatusUI', 'SessionThemeTint',
    'SessionTransport', 'SessionLabel', 'UIFlags', 'API', 'CloudeWeb',
] as const;

function installLegacy(files: string[]): void {
    const context: Record<string, unknown> = { console };
    context.window = context;
    context.globalThis = context;
    context.CloudeGlyphs = { glyphSvg };
    context.document = document;
    vm.createContext(context);
    for (const file of files) {
        vm.runInContext(
            fs.readFileSync(path.join(repoRoot, 'client', 'js', file), 'utf8'),
            context,
        );
    }
    for (const key of Object.keys(context)) {
        if ((INSTALLED as readonly string[]).includes(key)) {
            (window as unknown as Record<string, unknown>)[key] = context[key];
        }
    }
}

beforeEach(() => {
    for (const key of INSTALLED) {
        delete (window as unknown as Record<string, unknown>)[key];
    }
});

afterEach(() => {
    for (const key of INSTALLED) {
        delete (window as unknown as Record<string, unknown>)[key];
    }
});

describe('actionsFor carries the shared rule across unchanged', () => {
    beforeEach(() => {
        installLegacy(['session-status-ui.js', 'session-row-actions.js']);
    });

    function legacy(): {
        ACTION_CLOSE: string; ACTION_REMOVE: string; ACTION_RESTART: string;
        LIVE_STATUSES: string[];
        actionsFor(status: string | null): string[];
    } {
        return (window as unknown as { SessionRowActions: never }).SessionRowActions;
    }

    test('EVERY measured-live status is offered restart, through the host', () => {
        const host = browserRunningHost();
        const mod = legacy();
        expect(mod.LIVE_STATUSES.length).toBeGreaterThan(3);
        for (const status of mod.LIVE_STATUSES) {
            const ids = host.actionsFor(status).map((a) => a.id);
            expect(ids, `status ${status}`).toContain(mod.ACTION_RESTART);
            expect(ids, `status ${status}`).toContain(mod.ACTION_CLOSE);
            expect(ids, `status ${status}`).not.toContain(mod.ACTION_REMOVE);
        }
    });

    test('the host answers EXACTLY what the module answers, id for id and in order', () => {
        const host = browserRunningHost();
        const mod = legacy();
        for (const status of [...mod.LIVE_STATUSES, 'dead', 'unknown', null, '']) {
            expect(
                host.actionsFor(status).map((a) => a.id),
                `status ${String(status)}`,
            ).toEqual(mod.actionsFor(status));
        }
    });

    test('a DEAD row is restart then remove, and `unknown` is close alone', () => {
        const host = browserRunningHost();
        expect(host.actionsFor('dead').map((a) => a.id)).toEqual(['restart', 'remove']);
        expect(host.actionsFor('unknown').map((a) => a.id)).toEqual(['close']);
    });

    test('each descriptor names a glyph that really exists', () => {
        const host = browserRunningHost();
        for (const status of ['idle', 'dead', 'unknown']) {
            for (const action of host.actionsFor(status)) {
                expect(glyphSvg(action.glyph), `${status}/${action.id}`)
                    .toContain('<svg');
            }
        }
    });

    test('only restart carries the extra class, and it carries it every time', () => {
        const host = browserRunningHost();
        for (const status of ['idle', 'working', 'dead']) {
            for (const action of host.actionsFor(status)) {
                const expected = action.id === 'restart'
                    ? 'session-row-action-restart' : '';
                expect(action.extraClass, `${status}/${action.id}`).toBe(expected);
            }
        }
    });

    test('THE MODULE MISSING IS A REFUSAL, not an invented control', () => {
        // could not be read
        delete (window as unknown as Record<string, unknown>).SessionRowActions;
        expect(browserRunningHost().actionsFor('idle')).toEqual([]);
    });
});

describe('the other pass-throughs carry their answers unchanged too', () => {
    test('requiresConfirm and actionLabel come from the shared module', () => {
        installLegacy(['session-status-ui.js', 'session-row-actions.js']);
        const host = browserRunningHost();
        const mod = (window as unknown as {
            SessionRowActions: {
                ACTION_CLOSE: string; ACTION_REMOVE: string; ACTION_RESTART: string;
                labelFor(a: string): string; requiresConfirm(a: string): boolean;
            };
        }).SessionRowActions;
        for (const action of [mod.ACTION_CLOSE, mod.ACTION_REMOVE, mod.ACTION_RESTART]) {
            expect(host.actionLabel(action)).toBe(mod.labelFor(action));
            expect(host.requiresConfirm(action)).toBe(mod.requiresConfirm(action));
        }
        expect(host.requiresConfirm(mod.ACTION_RESTART)).toBe(false);
        expect(host.requiresConfirm(mod.ACTION_CLOSE)).toBe(true);
    });

    test('a missing confirm module answers NO, never yes', async () => {
        await expect(browserRunningHost().confirmAction('close', 'api'))
            .resolves.toBe(false);
    });

    test('a missing picker is reported as absent, not as a decline', () => {
        expect(browserRunningHost().hasRestartPicker()).toBe(false);
    });

    test('the theme lookup is the SHARED one, and answers null when it cannot tell', () => {
        installLegacy(['session-theme-tint.js']);
        const host = browserRunningHost();
        expect(host.themeColors('dracula')).toBeNull();
    });

    test('the label limit comes from the module that mirrors the server', () => {
        installLegacy(['session-label.js']);
        const mod = (window as unknown as {
            SessionLabel: { LABEL_MAX_CHARS: number };
        }).SessionLabel;
        expect(browserRunningHost().labelMaxChars()).toBe(mod.LABEL_MAX_CHARS);
        expect(mod.LABEL_MAX_CHARS).toBeGreaterThan(64);
    });

    test('and a missing label module refuses every value rather than accepting one', () => {
        expect(browserRunningHost().validateLabel('anything').ok).toBe(false);
    });
});

describe('the plugin bridge', () => {
    test('NO BUNDLE IS A REFUSAL, and an EMPTY LIST is not the same thing', () => {
        // failed to load
        expect(browserRunningHost().cardActions('cloude_api', false)).toEqual([]);
    });

    test('the flags block defaults the control ON when nothing can answer', () => {
        const seen: Array<{ flags: Record<string, boolean> }> = [];
        (window as unknown as Record<string, unknown>).CloudeWeb = {
            sessionCardMenuItems: (_row: unknown, ctx: { flags: Record<string, boolean> }) => {
                seen.push({ flags: ctx.flags });
                return [];
            },
        };
        browserRunningHost().cardActions('cloude_api', false);
        expect(seen[0]?.flags.show_mark_unread_control).toBe(true);
    });

    test('and it passes a FALSE flag through when one is measured', () => {
        const seen: Array<Record<string, boolean>> = [];
        (window as unknown as Record<string, unknown>).UIFlags = {
            showMarkUnreadControl: () => false,
        };
        (window as unknown as Record<string, unknown>).CloudeWeb = {
            sessionCardMenuItems: (_row: unknown, ctx: { flags: Record<string, boolean> }) => {
                seen.push(ctx.flags);
                return [];
            },
        };
        browserRunningHost().cardActions('cloude_api', false);
        expect(seen[0]?.show_mark_unread_control).toBe(false);
    });

    test('the row it describes carries the NAME and the painted unread state', () => {
        const seen: Array<{ name: string; unread: boolean }> = [];
        (window as unknown as Record<string, unknown>).CloudeWeb = {
            sessionCardMenuItems: (r: { name: string; unread: boolean }) => {
                seen.push(r);
                return [];
            },
        };
        browserRunningHost().cardActions('cloude_api', true);
        expect(seen[0]).toEqual({ name: 'cloude_api', unread: true });
    });

    test('a working row drops mark unread, an unread working row and an idle row keep it', () => {
        (window as unknown as Record<string, unknown>).CloudeWeb = {
            sessionCardMenuItems: () => [{ id: 'mark-unread', label: 'mark unread' }],
        };
        const h = browserRunningHost();
        expect(h.cardActions('a', false, 'working')).toEqual([]);
        expect(h.cardActions('a', false, 'working_subagent')).toEqual([]);
        expect(h.cardActions('a', true, 'working')).toHaveLength(1);
        expect(h.cardActions('a', false, 'idle')).toHaveLength(1);
    });
});

describe('resolveSessionId says when it cannot tell (u141-03)', () => {
    test('a listing that fails rejects, instead of answering "no bound session"', async () => {
        (window as unknown as Record<string, unknown>).API = {
            listSessions: async () => { throw new Error('listing down'); },
        };
        await expect(browserRunningHost().resolveSessionId('carnivore_api')).rejects.toThrow('listing down');
    });

    test('a listing with no match still answers null, a real "not bound"', async () => {
        (window as unknown as Record<string, unknown>).API = { listSessions: async () => [{ tmux_session: 'other' }] };
        expect(await browserRunningHost().resolveSessionId('carnivore_api')).toBeNull();
    });
});
