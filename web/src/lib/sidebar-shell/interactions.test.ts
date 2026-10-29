/** @vitest-environment jsdom */
import { beforeAll, describe, expect, it } from 'vitest';
import { canonicalDom } from './legacy-fixture';
import { legacyAnswer, suiteOfTest } from './goldens';
import {
    loadInteractions, recorded, settle, startRun, type Harness, type RunOptions,
} from './interaction-fixture';
import { SHELL_ATTR, sidebarShell } from './shell.svelte';


interface Snapshot {
    label: string;
    list: string;
    menu: string | null;
    focus: string;
    collapsed: string[];
    groups: string;
}

type Steps = (h: Harness, g: Gestures) => Promise<void>;

interface Gestures {
    click(selector: string): Promise<void>;
    key(key: string, target?: Element | null): Promise<void>;
    pick(label: string): Promise<void>;
    type(value: string): Promise<void>;
    snap(label: string): void;
    el(selector: string): Element;
}

let w: Record<string, any>;

function focusOf(): string {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return 'body';
    if (el.closest('.acm-menu') && el.dataset['node']) return `item:${el.querySelector('.acm-label')?.textContent ?? ''}`;
    return [el.tagName, el.className, el.getAttribute('data-menu-index'), el.getAttribute('data-group-toggle')].join('|');
}

function menuItems(): HTMLElement[] {
    return Array.from(document.querySelectorAll<HTMLElement>('.acm-menu[data-level="0"] [data-node]'));
}

interface Run {
    snaps: Snapshot[];
    events: unknown[];
    shell: string | null;
}

async function play(steps: Steps, o: RunOptions = {}): Promise<Run> {
    const mode = 'shell';
    const h = startRun(o);
    const shell = h.list.getAttribute(SHELL_ATTR);
    const snaps: Snapshot[] = [];
    const el = (selector: string): Element => {
        const found = document.querySelector(selector);
        if (!found) throw new Error(`${mode}: nothing matches ${selector}`);
        return found;
    };
    const g: Gestures = {
        el,
        async click(selector) {
            el(selector).dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, cancelable: true }));
            (el(selector) as HTMLElement).click();
            await settle();
        },
        async key(key, target) {
            const at = target || document.activeElement || document.body;
            at.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
            await settle();
        },
        async pick(label) {
            const item = menuItems().find((b) => b.querySelector('.acm-label')?.textContent === label);
            if (!item) throw new Error(`${mode}: no menu item ${label}`);
            item.click();
            await settle();
        },
        async type(value) {
            const input = el('#session-sidebar-list .session-sidebar-rename-input') as HTMLInputElement;
            input.value = value;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            await settle();
        },
        snap(label) {
            const menu = document.querySelector('.acm-menu');
            const state = w.SessionSidebarArrangement.current();
            snaps.push({
                label,
                list: canonicalDom(h.list),
                menu: menu ? menuItems().map((b) => `${b.querySelector('.acm-label')?.textContent ?? ''}${b.getAttribute('aria-disabled') ? ` (${b.getAttribute('data-tooltip') ?? 'inert'})` : ''}`).join('|') : null,
                focus: focusOf(),
                collapsed: (state.collapsed || []).slice(),
                groups: JSON.stringify(h.groups()),
            });
        },
    };
    await steps(h, g);
    g.snap('end');
    w.SessionSidebarGroupActions.closeMenu();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    const input = document.querySelector('#session-sidebar-list .session-sidebar-rename-input') as HTMLInputElement | null;
    if (input) input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    return { snaps, events: recorded().slice(), shell };
}

function legacyRun(run: Run): Run {
    return legacyAnswer(suiteOfTest(), { ...run, shell: null });
}

async function same(steps: Steps, o: RunOptions = {}): Promise<Run> {
    const svelte = await play(steps, o);
    const legacy = legacyRun(svelte);
    expect(legacy.shell).toBeNull();
    expect(svelte.shell).toBe('svelte');
    expect(svelte.events).toEqual(legacy.events);
    const around = (snaps: Snapshot[]) => snaps.map(({ menu, focus, ...rest }) => ({ ...rest, menu: menu === null, focus: focus.startsWith('item:') || focus.includes('session-sidebar-group-menu__item') ? 'menu' : focus }));
    expect(around(svelte.snaps)).toEqual(around(legacy.snaps));
    return svelte;
}

const GROUP_KEBAB = (uuid: string) => `#session-sidebar-list [data-group-menu="${uuid}"]`;
const PROJECT_KEBAB = (key: string) => `#session-sidebar-list [data-project-menu="${key}"]`;
const TOGGLE = (key: string) => `#session-sidebar-list [data-group-toggle="${key}"]`;
const INPUT = '#session-sidebar-list .session-sidebar-rename-input';

beforeAll(() => {
    w = loadInteractions(sidebarShell);
});

describe('folding from a heading', () => {
    it('a group folds and unfolds, and says so', async () => {
        const run = await same(async (_h, g) => {
            await g.click(TOGGLE('g:g1'));
            g.snap('folded');
            await g.click(TOGGLE('g:g1'));
        });
        expect(run.snaps[0]!.collapsed).toEqual(['g:g1']);
        expect(run.events).toContainEqual(['live', 'g:g1 group collapsed']);
    });

    it('a project band and a company heading fold', async () => {
        const run = await same(async (_h, g) => {
            await g.click(TOGGLE('p:20'));
            g.snap('project folded');
            await g.click(TOGGLE('c:orphaned'));
            g.snap('company folded');
            await g.click(TOGGLE('c:orphaned'));
        });
        expect(run.snaps[1]!.collapsed).toContain('c:orphaned');
        expect(run.events).toContainEqual(['live', 'orphaned projects group collapsed']);
    });
});

describe('the group heading menu', () => {
    it('opens under the kebab with its first item focused; Escape and a click outside close it', async () => {
        const run = await same(async (_h, g) => {
            await g.click(GROUP_KEBAB('g2'));
            g.snap('open');
            await g.key('Escape');
            (document.activeElement as HTMLElement | null)?.blur();
            g.snap('escaped');
            await g.click(GROUP_KEBAB('g2'));
            await g.click('#session-sidebar-live');
        });
        expect(run.snaps[0]!.menu).toContain('move up');
        expect(run.snaps[0]!.focus).toBe('item:rename');
        expect(run.snaps[2]!.menu).toBeNull();
    });

    it('Escape puts focus back on the kebab it opened from (the shell only)', async () => {
        const run = await play(async (_h, g) => {
            await g.click(GROUP_KEBAB('g2'));
            await g.key('Escape');
            g.snap('escaped');
        });
        expect(run.snaps[0]!.menu).toBeNull();
        expect(run.snaps[0]!.focus).toBe('BUTTON|oc-ibtn oc-ibtn--bare session-sidebar-group__menu||');
    });

    it('arrow keys move between the items (the shell only)', async () => {
        const run = await play(async (_h, g) => {
            await g.click(GROUP_KEBAB('g2'));
            await g.key('ArrowDown');
            g.snap('down');
            await g.key('End');
            g.snap('end key');
            await g.key('ArrowDown');
            g.snap('wrapped');
            await g.key('Escape');
        });
        expect(run.snaps.map((s) => s.focus.split(' (')[0])).toEqual(['item:add', 'item:remove', 'item:rename', 'BUTTON|oc-ibtn oc-ibtn--bare session-sidebar-group__menu||']);
    });

    it('move up on the first group and move down on the last stay in the menu, inert, with the reason inline', async () => {
        const run = await play(async (_h, g) => {
            await g.click(GROUP_KEBAB('g1'));
            g.snap('first');
            await g.click(GROUP_KEBAB('g3'));
            g.snap('last');
        });
        expect(run.snaps[0]!.menu).toContain('move up (already first)');
        expect(run.snaps[0]!.menu).toContain('move down|');
        expect(run.snaps[1]!.menu).toContain('move down (already last)');
        expect(run.snaps[1]!.menu).toContain('move up|');
    });

    it('a right-click on the heading opens the very same menu as its kebab, at the pointer, and the browser menu stays away', async () => {
        let prevented = false;
        const run = await play(async (_h, g) => {
            await g.click(GROUP_KEBAB('g2'));
            g.snap('kebab');
            await g.key('Escape');
            const row = g.el(TOGGLE('g:g2'));
            const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 50 });
            row.dispatchEvent(event);
            prevented = event.defaultPrevented;
            await settle();
            g.snap('right-click');
        });
        expect(prevented).toBe(true);
        expect(run.snaps[1]!.menu, 'same items in the same order').toBe(run.snaps[0]!.menu);
        expect(run.snaps[1]!.menu).toContain('rename');
    });

    it('move down and move up send the whole new order', async () => {
        const run = await same(async (_h, g) => {
            await g.click(GROUP_KEBAB('g1'));
            await g.pick('move down');
            g.snap('down');
            await g.click(GROUP_KEBAB('g3'));
            await g.pick('move up');
        });
        expect(run.events).toContainEqual(['api', 'reorderSessionGroups', ['g2', 'g1', 'g3']]);
    });

    it('a refused move re-reads the groups and says why, on both surfaces', async () => {
        const run = await same(async (_h, g) => {
            await g.click(GROUP_KEBAB('g1'));
            await g.pick('move down');
        }, { failRoute: 'reorderSessionGroups' });
        expect(run.events).toContainEqual(['api', 'listSessionGroups']);
        expect(run.events.some((e) => (e as unknown[])[0] === 'failure')).toBe(true);
    });

    it('remove confirms, then removes; declining removes nothing', async () => {
        const run = await same(async (_h, g) => {
            await g.click(GROUP_KEBAB('g1'));
            await g.pick('remove (1 agent moves to its project or rogue agents)');
        });
        expect(run.events.some((e) => (e as unknown[])[0] === 'confirm')).toBe(true);
        expect(run.events).toContainEqual(['api', 'deleteSessionGroup', 'g1']);
        const declined = await same(async (_h, g) => {
            await g.click(GROUP_KEBAB('g3'));
            await g.pick('remove (1 agent moves to its project or rogue agents)');
        }, { confirm: false });
        expect(declined.events.some((e) => (e as unknown[])[1] === 'deleteSessionGroup')).toBe(false);
    });

    it('a refused remove says why', async () => {
        await same(async (_h, g) => {
            await g.click(GROUP_KEBAB('g2'));
            await g.pick('remove (1 agent moves to its project or rogue agents)');
        }, { failRoute: 'deleteSessionGroup' });
    });

    it('color and icon open the shared pickers beside the same kebab', async () => {
        const run = await same(async (_h, g) => {
            await g.click(GROUP_KEBAB('g2'));
            await g.pick('color');
            await g.click(GROUP_KEBAB('g2'));
            await g.pick('icon');
        });
        expect(run.events).toEqual([['colour-picker', 'g2', 'g2'], ['icon-picker', 'g2', 'g2']]);
    });

    it('sleep puts every awake session in the group to sleep', async () => {
        const run = await same(async (_h, g) => {
            await g.click(GROUP_KEBAB('g1'));
            await g.pick('sleep');
        });
        expect(run.events).toContainEqual(['api', 'sleepSession', 'su-cloude_b']);
    });
});

describe('renaming a heading in place', () => {
    const openRename = async (g: Gestures) => {
        await g.click(GROUP_KEBAB('g1'));
        await g.pick('rename');
    };

    it('the editor opens on the name, and Enter saves', async () => {
        const run = await same(async (_h, g) => {
            await openRename(g);
            g.snap('open');
            await g.type('renamed crew');
            await g.key('Enter', g.el(INPUT));
        });
        expect(run.snaps[0]!.list).toContain('session-sidebar-rename-input');
        expect(run.snaps[0]!.focus).toContain('session-sidebar-rename-input');
        expect(run.events).toContainEqual(['api', 'renameSessionGroup', 'g1', 'renamed crew']);
        expect(run.events).toContainEqual(['live', 'group renamed to renamed crew']);
    });

    it('Escape cancels, and an unchanged name writes nothing', async () => {
        const run = await same(async (_h, g) => {
            await openRename(g);
            await g.type('never saved');
            await g.key('Escape', g.el(INPUT));
            g.snap('cancelled');
            await openRename(g);
            await g.key('Enter', g.el(INPUT));
        });
        expect(run.events.some((e) => (e as unknown[])[0] === 'api')).toBe(false);
    });

    it('a name the label rule refuses stays in the box with the reason', async () => {
        const run = await same(async (_h, g) => {
            await openRename(g);
            await g.type('x'.repeat(300));
            await g.key('Enter', g.el(INPUT));
            g.snap('refused');
        });
        expect(run.snaps[0]!.list).toContain('at most');
    });

    it('a refusal from the server reopens the box with its reason', async () => {
        const run = await same(async (_h, g) => {
            await openRename(g);
            await g.type('taken');
            await g.key('Enter', g.el(INPUT));
            g.snap('refused');
        }, { failRoute: 'renameSessionGroup' });
        expect(run.snaps[0]!.list).toContain('rename failed: renameSessionGroup refused by the test');
    });

    it('leaving the box saves, and a click inside it never folds the band', async () => {
        const run = await same(async (_h, g) => {
            await openRename(g);
            await g.click(INPUT);
            g.snap('clicked inside');
            await g.type('left behind');
            (g.el(INPUT) as HTMLInputElement).blur();
            await settle();
        });
        expect(run.snaps[0]!.collapsed).toEqual([]);
        expect(run.events).toContainEqual(['api', 'renameSessionGroup', 'g1', 'left behind']);
    });

    it('a repaint while typing keeps the text, the caret and the focus (the shell only)', async () => {
        const run = await play(async (h, g) => {
            await openRename(g);
            await g.type('half typed');
            const input = g.el(INPUT) as HTMLInputElement;
            input.setSelectionRange(4, 4);
            input.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowLeft', bubbles: true }));
            (h.rows[0] as Record<string, unknown>).status = 'working';
            h.w.SessionSidebar.repaint();
            await settle();
            const again = g.el(INPUT) as HTMLInputElement;
            expect(again).toBe(input);
            expect(again.value).toBe('half typed');
            expect(again.selectionStart).toBe(4);
            g.snap('after repaint');
        });
        expect(run.snaps[0]!.focus).toContain('session-sidebar-rename-input');
        expect(run.events.some((e) => (e as unknown[])[0] === 'api')).toBe(false);
    });

    it('an edit whose heading stops drawing is dropped, and a new one can open', async () => {
        await play(async (h, g) => {
            await openRename(g);
            h.w.SessionSidebarGroupStore.apply({ status: 'ok', groups: h.groups().filter((x) => x.group_uuid !== 'g1') });
            h.w.SessionSidebar.repaint();
            await settle();
            expect(document.querySelector(INPUT)).toBeNull();
            await g.click(GROUP_KEBAB('g3'));
            await g.pick('rename');
            expect(document.querySelector(INPUT)).not.toBeNull();
        });
    });

    it('F2 on a focused group heading opens the same editor', async () => {
        const run = await same(async (_h, g) => {
            const header = g.el(TOGGLE('g:g3')) as HTMLElement;
            header.focus();
            await g.key('F2', header);
            g.snap('f2');
        });
        expect(run.snaps[0]!.list).toContain('session-sidebar-rename-input');
    });
});

describe('the project heading menu', () => {
    it('opens with rename, sleep, load blueprint and remove', async () => {
        const run = await same(async (_h, g) => {
            await g.click(PROJECT_KEBAB('p:20'));
            g.snap('open');
            await g.pick('load blueprint');
        });
        expect(run.events).toEqual([['blueprints']]);
    });

    it('rename saves through PATCH /projects/{name}', async () => {
        const run = await same(async (_h, g) => {
            await g.click(PROJECT_KEBAB('p:20'));
            await g.pick('rename');
            g.snap('open');
            await g.type('Studios');
            await g.key('Enter', g.el(INPUT));
        });
        expect(run.events).toContainEqual(['api', 'updateProject', 'Studio', { newName: 'Studios' }]);
    });

    it('sleep skips an asleep row', async () => {
        const run = await same(async (_h, g) => {
            await g.click(PROJECT_KEBAB('p:20'));
            await g.pick('sleep');
        });
        const slept = run.events.filter((e) => (e as unknown[])[1] === 'sleepSession').map((e) => (e as unknown[])[2]);
        expect(slept).toEqual(['su-cloude_c', 'su-cloude_e']);
    });

    it('remove closes every session the right way, then archives', async () => {
        const run = await same(async (_h, g) => {
            await g.click(PROJECT_KEBAB('p:20'));
            await g.pick('remove');
        });
        const api = run.events.filter((e) => (e as unknown[])[0] === 'api').map((e) => (e as unknown[]).slice(1));
        expect(api).toEqual([
            ['destroySession', 'ses_cloude_c'], ['deleteSessionRecord', 'su-cloude_d'],
            ['destroyExternalSession', 'cloude_e'], ['archiveProject', 'Studio'],
        ]);
    });

    it('one failed close keeps the project', async () => {
        const run = await same(async (_h, g) => {
            await g.click(PROJECT_KEBAB('p:20'));
            await g.pick('remove');
        }, { failRoute: 'destroyExternalSession' });
        expect(run.events.some((e) => (e as unknown[])[1] === 'archiveProject')).toBe(false);
    });
});

describe('the comparison can fail', () => {
    it('NEGATIVE CONTROL: a gesture only one renderer performs is seen', async () => {
        const svelte = await play(async (_h, g) => {
            await g.click(TOGGLE('g:g1'));
            await g.click(TOGGLE('p:10'));
        });
        const legacy = legacyRun(svelte);
        expect(svelte.snaps).not.toEqual(legacy.snaps);
        expect(svelte.events).not.toEqual(legacy.events);
    });

    it('NEGATIVE CONTROL: the legacy handlers really stand down for a shell heading', async () => {
        const run = await play(async (_h, g) => { await g.click(TOGGLE('g:g2')); });
        expect(run.snaps[0]!.collapsed).toEqual(['g:g2']);
        expect(run.events.filter((e) => (e as unknown[])[0] === 'live')).toHaveLength(1);
    });
});
