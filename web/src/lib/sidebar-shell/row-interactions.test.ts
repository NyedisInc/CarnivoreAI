/** @vitest-environment jsdom */
import { beforeAll, describe, expect, it } from 'vitest';
import { loadRowInteractions, settle } from './row-interaction-fixture';
import { legacyRun, names, play, ROW, same } from './row-interaction-play';
import { sidebarShell } from './shell.svelte';
import { claimOpenMenu } from '../drawer-tabs/open-menu';
import { openItemMenuContext } from '../item-menu/open.svelte';
import { closeRowMenu, rowMenuIsOpen } from '../item-menu/row-open';

const openFor = (): string | null => (openItemMenuContext() as { name?: string } | null)?.name ?? null;

let w: Record<string, any>;

beforeAll(() => {
    w = loadRowInteractions(sidebarShell);
});

describe('selecting and opening a row', () => {
    it('a click on an open session opens it through GET and returns to its terminal', async () => {
        const { svelte } = await same(w, async (g) => { await g.click(`${ROW('cloude_b')} .session-sidebar-row-name`); });
        expect(names(svelte)).toEqual(['api.getSession', 'close-after-switch', 'app.returnToExistingTerminal']);
    });

    it('Enter and Space on a focused row open it the same way', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.key(ROW('cloude_b'), 'Enter');
            await g.key(ROW('cloude_c'), ' ');
        });
        expect(names(svelte).filter((n) => n === 'api.getSession')).toHaveLength(2);
    });

    it('a click on the session already attached only closes the drawer', async () => {
        const { svelte } = await same(w, async (g) => {
            w.SessionSidebar._activeTmuxName = 'cloude_b';
            await g.click(ROW('cloude_b'));
        });
        expect(names(svelte)).toEqual(['close-after-switch']);
    });

    it('a click on an external row adopts it and announces the new session', async () => {
        const { svelte } = await same(w, async (g) => { await g.click(ROW('cloude_x')); });
        expect(names(svelte)).toEqual(['api.adoptSession', 'close-after-switch', 'session-created']);
    });

    it('two clicks before the first answer: only the second paints (the navigation generation)', async () => {
        const { svelte } = await same(w, async (g) => {
            g.el(ROW('cloude_b')).click();
            g.el(ROW('cloude_c')).click();
            await settle();
        });
        expect(svelte.events).toEqual([
            ['api.getSession', 'ses_cloude_b', { includeScrollback: true, parallelHistory: true }],
            ['api.getSession', 'ses_cloude_c', { includeScrollback: true, parallelHistory: true }],
            ['close-after-switch'],
            ['app.returnToExistingTerminal', { id: 'x' }],
        ]);
    });

    it('a pending click is painted as the selected row until it lands', async () => {
        const { svelte } = await same(w, async (g) => {
            const api = w.API.getSession;
            w.API.getSession = () => new Promise(() => {});
            try {
                g.el(ROW('cloude_c')).click();
                await settle();
                expect(g.el(ROW('cloude_c')).getAttribute('aria-selected')).toBe('true');
                expect(g.el(ROW('cloude_b')).getAttribute('aria-selected')).toBe('false');
            } finally {
                w.API.getSession = api;
                w.SessionSidebar._pendingSelection = null;
            }
        });
        expect(svelte.dom).toContain('aria-selected="true"');
    });

    it('a switch that fails says so in the same alert, and clears the pending pick', async () => {
        const api = w.API.getSession;
        const alerts: string[] = [];
        const alertWas = window.alert;
        w.API.getSession = async () => { throw new Error('gone'); };
        window.alert = (text?: unknown) => { alerts.push(String(text)); };
        try {
            await same(w, async (g) => { await g.click(ROW('cloude_b')); });
            expect(alerts).toEqual(['error: failed to switch agent: gone']);
            expect(w.SessionSidebar._pendingSelection).toBeNull();
        } finally {
            w.API.getSession = api;
            window.alert = alertWas;
        }
    });

    it('a click on an asleep row wakes nothing, it arms the wake button (#1505)', async () => {
        // the legacy twin
        const svelte = await play(w, async (g) => {
            await g.click(ROW('cloude_z'));
            expect(g.has(`${ROW('cloude_z')} .session-sidebar-row-wake-arm`)).toBe(true);
        });
        expect(svelte.events).toEqual([]);
    });
});

describe('the inline controls and chips', () => {
    it('the pin pins (the row moves to PINNED), and the pinned copy\'s pin unpins it', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.click(`${ROW('cloude_c')} [data-pin-session]`);
            expect(g.has('.session-sidebar-group[data-group="pinned"] .session-sidebar-row[data-name="cloude_c"]')).toBe(true);
            await g.click('.session-sidebar-group[data-group="pinned"] [data-pin-session="cloude_c"]');
        });
        expect(svelte.dom).not.toContain('data-band="pinned"');
        expect(svelte.live).toBe('cloude_c unpinned');
    });

    it('the keep-awake cup turns keep-awake off (#559)', async () => {
        const { svelte } = await same(w, async (g) => { await g.click(`${ROW('cloude_c')} [data-keep-awake-session]`); });
        expect(svelte.events).toContainEqual(['keep-awake', 'cloude_c', false]);
    });

    it('the subagent chip and the timer chip open their lists, and never open the row', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.click(`${ROW('cloude_a')} [data-subagents-session-id]`);
            await g.click(`${ROW('cloude_a')} [data-timers-session-id]`);
        });
        expect(names(svelte)).toEqual(['subagents.open', 'timers.open']);
    });

    it('the share mark opens the share dialog, then re-reads the drawer', async () => {
        const { svelte } = await same(w, async (g) => { await g.click(`${ROW('cloude_a')} [data-share-session-id]`); });
        expect(names(svelte)).toEqual(['plugin.runCplug', 'refetch']);
    });

    it('a dead row: remove confirms then destroys; restart opens the picker', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.click(`${ROW('cloude_d')} [data-session-action="remove"]`);
            await g.click(`${ROW('cloude_d')} [data-session-action="restart"]`);
        });
        expect(names(svelte)).toEqual(['app.confirm', 'api.destroySession', 'refetch', 'restart-picker.open']);
    });
});

describe('the shared row menu', () => {
    const PANEL = '#session-row-menu-panel';

    it('the kebab opens the one shared menu for that row, on both renderers', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.click(`${ROW('cloude_b')} [data-row-menu]`);
            expect(document.querySelector(PANEL)).not.toBeNull();
            expect(openFor()).toBe('cloude_b');
            expect(document.activeElement, 'focus starts on the menu\'s first item').toBe(document.querySelector(`${PANEL} [data-node]`));
        }, { differs: ['focus'] });
        expect(svelte.events).toEqual([]);
    });

    it('a right click on the row opens the same menu and never opens the row', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.contextmenu(`${ROW('cloude_c')} .session-sidebar-row-name`);
            expect(openFor()).toBe('cloude_c');
            expect(document.activeElement, 'focus starts on the menu\'s first item').toBe(document.querySelector(`${PANEL} [data-node]`));
        }, { differs: ['focus'] });
        expect(svelte.events).toEqual([]);
    });

    it('a right click and the kebab open the same list of items for a row, and another menu opening closes it (one at a time)', async () => {
        w.CloudeWeb = { ...(w.CloudeWeb || {}), openMenu: { claim: claimOpenMenu } };
        const ids = (): string[] => Array.from(document.querySelectorAll(`${PANEL} [data-node]`), (el) => el.getAttribute('data-node') ?? '');
        let viaKebab: string[] = [];
        let viaRightClick: string[] = [];
        await play(w, async (g) => {
            await g.click(`${ROW('cloude_c')} [data-row-menu]`);
            viaKebab = ids();
            closeRowMenu();
            await g.contextmenu(`${ROW('cloude_c')} .session-sidebar-row-name`);
            viaRightClick = ids();
            expect(rowMenuIsOpen()).toBe(true);
            const release = claimOpenMenu(() => {});
            expect(rowMenuIsOpen(), 'the row panel closed when another menu opened').toBe(false);
            release();
        });
        expect(viaKebab.length).toBeGreaterThan(0);
        expect(viaRightClick).toEqual(viaKebab);
    });

    it('the menu\'s rename opens the row\'s inline editor, and Enter saves', async () => {
        const proto = HTMLElement.prototype as unknown as { checkVisibility?: () => boolean };
        const had = Object.getOwnPropertyDescriptor(proto, 'checkVisibility');
        proto.checkVisibility = () => true;
        try {
            const { svelte } = await same(w, async (g) => {
                await g.click(`${ROW('cloude_b')} [data-row-menu]`);
                const item = document.querySelector(`${PANEL} [data-node="rename"]`) as HTMLElement | null;
                expect(item).not.toBeNull();
                item!.click();
                await settle();
                expect(g.has('.session-sidebar-rename-input')).toBe(true);
                await g.type('from the menu');
                await g.boxKey('Enter');
            });
            expect(svelte.events).toContainEqual(['api.renameSession', 'ses_cloude_b', 'from the menu']);
            expect(svelte.live).toBe('renamed b to from the menu');
        } finally {
            if (had) Object.defineProperty(proto, 'checkVisibility', had); else delete proto.checkVisibility;
        }
    });
});

describe('the comparison can fail', () => {
    it('NEGATIVE CONTROL: a gesture that lands differently is seen', async () => {
        const svelte = await play(w, async (g) => { await g.click(ROW('cloude_x')); });
        const legacy = legacyRun(svelte);
        expect(svelte.events).not.toEqual(legacy.events);
    });

    it('NEGATIVE CONTROL: a Svelte row missing its pin data attribute breaks the pin', async () => {
        const run = await play(w, async (g) => {
            g.el(`${ROW('cloude_c')} [data-pin-session]`).removeAttribute('data-pin-session');
            await g.click(`${ROW('cloude_c')} .session-sidebar-row-pin`);
        });
        expect(run.dom).not.toContain('data-band="pinned"');
    });

    it('the shell owns its rows, so a key acts exactly once (the legacy listener that could act a second time is deleted)', async () => {
        const once = await play(w, async (g) => {
            expect(sidebarShell.owns(g.el(ROW('cloude_c')))).toBe(true);
            await g.key(ROW('cloude_c'), 'p');
        });
        expect(once.live).toBe('cloude_c pinned to the top');
        expect(JSON.parse(once.arrangement).pinned).toEqual(['cloude_c']);
    });
});
