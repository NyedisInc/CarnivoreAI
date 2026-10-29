/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { closeItemMenu, itemMenuState } from '../item-menu/open.svelte';
import '../item-menu/menus/all';
import { itemMenu } from '../item-menu/registry';
import { createGroupThenAssign } from '../sidebar-shell/group-assign';
import * as GroupStore from './group-store';
import { commitAssignment } from '../sidebar-shell/group-assign';
import { init, openPickerFor } from './group-actions';

installPopoverPolyfill();

type Win = Record<string, any>;
const win = globalThis as unknown as Win;

const group = (uuid: string, name: string, members: string[]) => ({
    group_uuid: uuid, name, position: 0, members, member_session_uuids: [], colour: null, gradient: null, animation: 'none', icon: null,
});
const body = () => ({ status: 'ok', groups: [group('g1', 'research', ['cloude_a']), group('g2', 'ops', [])] });

let calls: Array<[string, ...unknown[]]>;
let reports: string[];
let live: HTMLElement;
let anchor: HTMLElement;

beforeEach(() => {
    calls = [];
    reports = [];
    document.body.innerHTML = '<div id="session-sidebar-live"></div>';
    live = document.getElementById('session-sidebar-live')!;
    anchor = document.createElement('button');
    document.body.append(anchor);
    GroupStore.apply(body());
    win.SessionSidebar = { repaint: () => calls.push(['repaint']) };
    win.WriteFailureNotice = { report: (text: string) => reports.push(text) };
    win.API = {
        assignSessionGroup: async (name: string, uuid: string | null) => { calls.push(['assign', name, uuid]); return body(); },
        listSessionGroups: async () => { calls.push(['list']); return body(); },
        createSessionGroup: async (name: string) => { calls.push(['create', name]); return { status: 'ok', groups: [...body().groups, group('g3', name, [])] }; },
    };
});

afterEach(() => {
    closeItemMenu();
    GroupStore.reset();
    delete win.SessionSidebar;
    delete win.WriteFailureNotice;
    delete win.API;
    delete win.TextPromptModal;
    document.body.replaceChildren();
});

function picker(name = 'cloude_a') {
    return itemMenu('grouppick', { name, anchor }, { close: () => {}, glyph: () => '' });
}

describe('the picker is an item of the one menu', () => {
    it('lists every group, then other, then new group, with the current one checked', () => {
        const built = picker()!;
        expect(built.ariaLabel).toBe('move cloude_a to a group');
        expect(built.nodes.map((n) => [n.label, n.checked])).toEqual([
            ['research', true], ['ops', false], ['other (no group)', false], ['new group...', undefined],
        ]);
    });

    it('an ungrouped session has "other" checked', () => {
        expect(picker('cloude_free')!.nodes.map((n) => n.checked)).toEqual([false, false, true, undefined]);
    });

    it('is null while the group model is unavailable, and opening says so instead of showing a menu', () => {
        GroupStore.markUnavailable('down');
        expect(picker()).toBeNull();
        openPickerFor(anchor, 'cloude_a');
        expect(itemMenuState.open).toBeNull();
        expect(reports).toEqual(['groups are unavailable, so this agent cannot be filed']);
        expect(live.textContent).toBe('groups are unavailable, so this agent cannot be filed');
    });

    it('opens through the item menu host and draws no menu markup of its own', () => {
        openPickerFor(anchor, 'cloude_a');
        flushSync();
        expect(itemMenuState.open?.type).toBe('grouppick');
        expect(document.querySelector('.session-sidebar-group-menu')).toBeNull();
        expect(document.getElementById('item-menu-host')).not.toBeNull();
    });
});

describe('every pick is one assign call', () => {
    it('a group, other and a failed write', async () => {
        const [research, ops, other] = picker()!.nodes;
        ops!.run!();
        await vi.waitFor(() => expect(calls.filter((c) => c[0] === 'assign')).toEqual([['assign', 'cloude_a', 'g2']]));
        expect(live.textContent).toBe('cloude_a moved to ops');
        other!.run!();
        await vi.waitFor(() => expect(calls.filter((c) => c[0] === 'assign')[1]).toEqual(['assign', 'cloude_a', null]));
        await vi.waitFor(() => expect(live.textContent).toBe('cloude_a moved to its project or rogue agents'));
        expect(research).toBeDefined();
    });

    it('a refused write snaps back from the server and says why on BOTH surfaces', async () => {
        win.API.assignSessionGroup = async () => { throw new Error('nope'); };
        expect(await commitAssignment('cloude_a', 'g2')).toBe(false);
        expect(calls.some((c) => c[0] === 'list')).toBe(true);
        expect(reports).toEqual(['could not move cloude_a: nope']);
        expect(live.textContent).toBe('could not move cloude_a: nope');
    });
});

describe('new group', () => {
    it('asks for a name, creates the group and files the session into it', async () => {
        win.TextPromptModal = { open: async () => 'infra' };
        await createGroupThenAssign('cloude_a');
        expect(calls.filter((c) => c[0] === 'create' || c[0] === 'assign')).toEqual([['create', 'infra'], ['assign', 'cloude_a', 'g3']]);
    });

    it('cancelling writes nothing; with no session it only creates; a refusal is said in words', async () => {
        win.TextPromptModal = { open: async () => null };
        await createGroupThenAssign('cloude_a');
        expect(calls.filter((c) => c[0] === 'create')).toEqual([]);
        win.TextPromptModal = { open: async () => 'infra' };
        await createGroupThenAssign(null);
        expect(live.textContent).toBe('group infra created');
        win.API.createSessionGroup = async () => { throw new Error('duplicate'); };
        await createGroupThenAssign(null);
        expect(reports).toEqual(['could not create the group: duplicate']);
    });
});

describe('the g key', () => {
    it('opens the same picker on a focused row, and ignores a modified g or a non-row target', () => {
        init();
        const row = document.createElement('div');
        row.className = 'session-sidebar-row';
        row.dataset['name'] = 'cloude_a';
        document.body.append(row);
        row.dispatchEvent(new KeyboardEvent('keydown', { key: 'g', ctrlKey: true, bubbles: true }));
        anchor.dispatchEvent(new KeyboardEvent('keydown', { key: 'g', bubbles: true }));
        expect(itemMenuState.open).toBeNull();
        const event = new KeyboardEvent('keydown', { key: 'g', bubbles: true, cancelable: true });
        row.dispatchEvent(event);
        flushSync();
        expect(event.defaultPrevented).toBe(true);
        expect(itemMenuState.open?.type).toBe('grouppick');
    });
});
