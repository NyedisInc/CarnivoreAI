/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, tick, unmount } from 'svelte';

const preview = vi.hoisted(() => vi.fn());
const launch = vi.hoisted(() => vi.fn());
vi.mock('./api', async (actual) => ({
    ...(await actual<typeof import('./api')>()),
    previewLaunch: preview,
    launchBlueprint: launch,
}));

const openSession = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/host', () => ({ openSession }));

import LaunchModal from './LaunchModal.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { LaunchPreviewResponse, LaunchResponse, MemberPreview } from './types';

function member(overrides: Partial<MemberPreview> = {}): MemberPreview {
    return {
        index: 0,
        label: 'agent 1',
        family: 'claude',
        family_name: null,
        folder: { mode: 'existing', path: '/work/api', worktree: null },
        project: null,
        skills: [],
        skill_roots_to_create: [],
        opening_prompt: false,
        problems: [],
        ...overrides,
    };
}

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    vi.clearAllMocks();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
    await tick();
}

async function open(uuid = 'bp-1', name = 'review team'): Promise<{ root: HTMLElement; closed: Array<boolean | null> }> {
    const target = document.createElement('div');
    document.body.append(target);
    const closed: Array<boolean | null> = [];
    mounted = mount(LaunchModal as never, { target, props: { uuid, name, close: (v: boolean | null) => closed.push(v) } as never });
    await settle();
    return { root: target, closed };
}

describe('D7: the launching stage', () => {
    test('says it is starting N sessions, never a fake numerator', async () => {
        const two: LaunchPreviewResponse = { blueprint_uuid: 'bp-1', name: 'review team', worktree_root: '/wt', members: [member(), member({ index: 1, label: 'agent 2' })] };
        preview.mockResolvedValueOnce(two);
        launch.mockImplementation(() => new Promise<LaunchResponse>(() => {}));
        const { root } = await open();
        expect(root.querySelector('[data-testid]')).toBeNull();
        (root.querySelector('[data-bp-confirm]') as HTMLButtonElement).click();
        await settle();
        expect(root.textContent).not.toMatch(/\(0 of/);
        expect(root.querySelector('[role="status"]')?.textContent).toContain('2');
    });
});

describe('D4: focus survives a stage change', () => {
    test('a footer swap that drops the clicked button never leaves focus on <body>', async () => {
        preview.mockResolvedValueOnce({ blueprint_uuid: 'bp-1', name: 'x', worktree_root: '/wt', members: [member()] });
        launch.mockImplementation(() => new Promise<LaunchResponse>(() => {}));
        const { root } = await open();
        const confirmBtn = root.querySelector('[data-bp-confirm]') as HTMLButtonElement;
        confirmBtn.focus();
        expect(document.activeElement).toBe(confirmBtn);
        confirmBtn.click();
        await settle();
        expect(document.activeElement).not.toBe(document.body);
        expect(document.querySelector('.modal-overlay')?.contains(document.activeElement)).toBe(true);

        const windowEscape = vi.fn();
        window.addEventListener('keydown', windowEscape);
        document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        window.removeEventListener('keydown', windowEscape);
        expect(windowEscape).not.toHaveBeenCalled();
    });
});

describe('D9: a finished solo launch', () => {
    test('offers "done" and "open session", never just "cancel"', async () => {
        preview.mockResolvedValueOnce({ blueprint_uuid: 'bp-1', name: 'solo', worktree_root: '/wt', members: [member()] });
        launch.mockResolvedValueOnce({
            blueprint_uuid: 'bp-1', name: 'solo', complete: true,
            members: [{ index: 0, label: 'agent 1', state: 'launched', folder: member().folder, project: null, skills: [], session: { id: 'ses_1', tmux_session: 'cloude_x', session_row_id: 1, session_uuid: 'u1' }, problem: null }],
            layout: null, layout_detail: 'a layout needs two or more launched sessions',
        } satisfies LaunchResponse);
        const { root, closed } = await open();
        (root.querySelector('[data-bp-confirm]') as HTMLButtonElement).click();
        await settle();
        const footerButtons = Array.from(root.querySelectorAll<HTMLButtonElement>('.modal-footer button'));
        const buttons = footerButtons.map((b) => b.textContent?.trim());
        expect(buttons.some((b) => b === 'cancel')).toBe(false);
        expect(buttons).toContain('done');
        expect(root.textContent).not.toContain('a layout needs two or more launched sessions');
        const openBtn = footerButtons.find((b) => b.textContent?.trim() === 'open');
        openBtn?.click();
        await settle();
        expect(openSession).toHaveBeenCalledWith('ses_1', 'cloude_x');
        expect(closed).toEqual([true]);
    });

    test('a member that was already running says so (issue #1320)', async () => {
        preview.mockResolvedValueOnce({ blueprint_uuid: 'bp-1', name: 'solo', worktree_root: '/wt', members: [member()] });
        launch.mockResolvedValueOnce({
            blueprint_uuid: 'bp-1', name: 'solo', complete: true,
            members: [{ index: 0, label: 'agent 1', state: 'reused', folder: member().folder, project: null, skills: [], session: { id: 'ses_1', tmux_session: 'cloude_x', session_row_id: 1, session_uuid: 'u1' }, problem: null }],
            layout: null, layout_detail: 'a layout needs two or more launched sessions',
        } satisfies LaunchResponse);
        const { root } = await open();
        (root.querySelector('[data-bp-confirm]') as HTMLButtonElement).click();
        await settle();
        expect(root.querySelector('[data-member-reused]')?.textContent).toBe('agent 1 was already running, kept as it is');
    });

    test('a multi-member launch with no layout still shows the server reason', async () => {
        preview.mockResolvedValueOnce({ blueprint_uuid: 'bp-1', name: 'pair', worktree_root: '/wt', members: [member(), member({ index: 1 })] });
        launch.mockResolvedValueOnce({
            blueprint_uuid: 'bp-1', name: 'pair', complete: false,
            members: [
                { index: 0, label: 'agent 1', state: 'launched', folder: member().folder, project: null, skills: [], session: { id: 'ses_1', tmux_session: 't1', session_row_id: 1, session_uuid: 'u1' }, problem: null },
                { index: 1, label: 'agent 2', state: 'failed', folder: member().folder, project: null, skills: [], session: null, problem: { step: 'create', code: 'x', detail: 'boom' } },
            ],
            layout: null, layout_detail: 'the launched sessions could not be saved as a layout: boom',
        } satisfies LaunchResponse);
        const { root } = await open();
        (root.querySelector('[data-bp-confirm]') as HTMLButtonElement).click();
        await settle();
        expect(root.textContent).toContain('the launched sessions could not be saved as a layout: boom');
    });
});

describe('an existing layout (issue #1327)', () => {
    const twoMembers = (): LaunchPreviewResponse => ({
        blueprint_uuid: 'bp-1', name: 'pair', worktree_root: '/wt', members: [member(), member({ index: 1 })] });
    const exists = () => new ApiError('conflict', 409, null, {
        detail: { code: 'layout_exists', detail: 'a layout named pair already exists', layout: { layout_uuid: 'l1', name: 'pair' } } });

    test('asks before updating, and cancelling launches nothing more', async () => {
        preview.mockResolvedValueOnce(twoMembers());
        launch.mockRejectedValueOnce(exists());
        const { root, closed } = await open();
        (root.querySelector('[data-bp-confirm]') as HTMLButtonElement).click();
        await settle();
        expect(root.querySelector('[data-layout-exists]')?.textContent).toBe('a layout named pair already exists. update it with these sessions?');
        const cancel = Array.from(root.querySelectorAll<HTMLButtonElement>('.modal-footer button')).find((b) => b.textContent?.trim() === 'cancel');
        cancel?.click();
        await settle();
        expect(launch).toHaveBeenCalledTimes(1);
        expect(closed).toEqual([false]);
    });

    test('a yes launches again with overwriteLayout and shows woken members and the update', async () => {
        preview.mockResolvedValueOnce(twoMembers());
        launch.mockRejectedValueOnce(exists());
        launch.mockResolvedValueOnce({
            blueprint_uuid: 'bp-1', name: 'pair', complete: true, layout_updated: true,
            members: [
                { index: 0, label: 'agent 1', state: 'woken', folder: member().folder, project: null, skills: [], session: { id: 's1', tmux_session: 't1', session_row_id: 1, session_uuid: 'u1' }, problem: null },
                { index: 1, label: 'agent 2', state: 'launched', folder: member().folder, project: null, skills: [], session: { id: 's2', tmux_session: 't2', session_row_id: 2, session_uuid: 'u2' }, problem: null },
            ],
            layout: { layout_uuid: 'l1', name: 'pair' }, layout_detail: null,
        } satisfies LaunchResponse);
        const { root } = await open();
        (root.querySelector('[data-bp-confirm]') as HTMLButtonElement).click();
        await settle();
        const update = Array.from(root.querySelectorAll<HTMLButtonElement>('.modal-footer button')).find((b) => b.textContent?.trim() === 'update layout');
        update?.click();
        await settle();
        expect(launch).toHaveBeenLastCalledWith('bp-1', expect.objectContaining({ overwriteLayout: true }));
        expect(root.querySelector('[data-member-woken]')?.textContent).toBe('agent 1 was asleep, woken up');
        expect(root.textContent).toContain('pair layout updated');
    });
});

describe('instructions_write notice', () => {
    const skill = (over: Record<string, unknown>) => ({
        item_id: 'pub/tidy', state: 'to_install', version: '1.0.0', needs_consent: false,
        consent_sheet: null, code: null, detail: null, refusal: null, ...over,
    });

    test('a skill whose own review edits the instruction files gets a notice, and no tick', async () => {
        preview.mockResolvedValueOnce({
            blueprint_uuid: 'bp-1', name: 'x', worktree_root: '/wt',
            members: [member({ skills: [skill({ instructions_write: true })] })],
        });
        const { root } = await open();
        const note = root.querySelector('[data-instructions-write-notice]');
        expect(note?.textContent).toContain('pub/tidy edits your agent instruction files, such as CLAUDE.md or AGENTS.md.');
        expect(root.querySelector('input[type="checkbox"]')).toBeNull();
    });

    test('the notice names the file from the details and says when there are more', async () => {
        preview.mockResolvedValueOnce({
            blueprint_uuid: 'bp-1', name: 'x', worktree_root: '/wt',
            members: [member({ skills: [skill({
                instructions_write: true,
                instructions_details: ['appends to ~/.claude/CLAUDE.md', '<b>x</b>'],
                instructions_more: 2,
            })] })],
        });
        const { root } = await open();
        const lines = [...root.querySelectorAll('[data-instructions-write-detail]')].map((n) => n.textContent);
        expect(lines).toEqual(['appends to ~/.claude/CLAUDE.md', '<b>x</b>']);
        expect(root.querySelector('[data-instructions-write-detail] b')).toBeNull();
        expect(root.querySelector('[data-instructions-write-more]')?.textContent).toBe('and 2 more in the review.');
    });

    test('NEGATIVE CONTROL: a skill without the flag has no notice', async () => {
        preview.mockResolvedValueOnce({
            blueprint_uuid: 'bp-1', name: 'x', worktree_root: '/wt',
            members: [member({ skills: [skill({ instructions_write: false })] })],
        });
        const { root } = await open();
        expect(root.querySelector('[data-instructions-write-notice]')).toBeNull();
    });
});

describe('script consent is one per skill (u131-01)', () => {
    const sheet = { digest: 'd1', body_sha: 'b1' };
    const scripted = (index: number): MemberPreview =>
        member({
            index,
            label: `agent ${index + 1}`,
            skills: [{ item_id: 'it-1', state: 'to_install', needs_consent: true, consent_sheet: sheet } as unknown as MemberPreview['skills'][number]],
        });

    test('ticking the skill for one member ticks it for every member that carries it, and one consent is sent', async () => {
        preview.mockResolvedValueOnce({ blueprint_uuid: 'bp-1', name: 'x', worktree_root: '/wt', members: [scripted(0), scripted(1)] });
        launch.mockImplementation(() => new Promise<LaunchResponse>(() => {}));
        const { root } = await open();
        const boxes = Array.from(root.querySelectorAll<HTMLInputElement>('.bp-launch__consent input[type="checkbox"]'));
        expect(boxes).toHaveLength(2);
        boxes[0]!.click();
        await settle();
        expect(boxes.map((b) => b.checked)).toEqual([true, true]);
        (root.querySelector('[data-bp-confirm]') as HTMLButtonElement).click();
        await settle();
        expect(launch.mock.calls[0]![1].consents).toEqual({ 'it-1': { digest: 'd1', body_sha: 'b1', scripts: true } });
    });
});
