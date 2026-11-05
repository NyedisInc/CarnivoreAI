/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import CommandConsent from './CommandConsent.svelte';
import type { CommandRow } from './api';
import { setLocale, t } from '../../i18n/index.svelte';

setLocale('en');

function render(rows: CommandRow[]) {
    const target = document.createElement('div');
    document.body.append(target);
    const handle = mount(CommandConsent, { target, props: { rows, t } });
    flushSync();
    return { target, handle };
}

function profileRow(parts: CommandRow['parts']): CommandRow {
    return { key: 'launch_profiles:0', kind: 'profile', id: 'claude-main', name: 'main', parts };
}

afterEach(() => {
    document.body.innerHTML = '';
});

describe('launch profile trust parts', () => {
    test('a change to skip_all is worded, warned about before what it was, and the kept default is said', () => {
        const { target, handle } = render([profileRow([
            { kind: 'permissions', value: 'skip_all', text: '--dangerously-skip-permissions', was: 'harness_default', was_text: '', tone: 'danger' },
            { kind: 'default', value: 'kept', text: 'claude-main' },
        ])]);
        const row = target.querySelector('[data-cb-command="launch_profiles:0"]')!;
        expect(row.textContent).toContain('skip all checks');
        expect(row.textContent).toContain('--dangerously-skip-permissions');
        expect(row.textContent).toContain('was harness default');
        const warning = row.querySelector('[data-cb-danger]')!;
        expect(warning.textContent).toContain('skips every permission prompt');
        const was = row.querySelector('[data-cb-was]')!;
        expect(warning.compareDocumentPosition(was) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(row.textContent).toContain('default launch profile');
        expect(row.textContent).toContain('stays the default');
        unmount(handle);
    });

    test('every posture is worded, not only skip_all', () => {
        const { target, handle } = render([profileRow([
            { kind: 'permissions', value: 'accept_edits', text: '--permission-mode acceptEdits', was: 'ask', was_text: '--permission-mode manual' },
        ])]);
        const row = target.querySelector('[data-cb-command="launch_profiles:0"]')!;
        expect(row.textContent).toContain('accept edits');
        expect(row.textContent).toContain('was ask first --permission-mode manual');
        expect(row.querySelector('[data-cb-danger]')).toBeNull();
        unmount(handle);
    });

    test('dangerous flags warn from the danger mark, and a harness switch shows what it was', () => {
        const { target, handle } = render([profileRow([
            { kind: 'harness', value: 'codex', text: '', was: 'claude', was_text: '' },
            { kind: 'flags', text: '-anever', tone: 'danger' },
        ])]);
        const row = target.querySelector('[data-cb-command="launch_profiles:0"]')!;
        expect(row.textContent).toContain('was claude');
        expect(row.querySelector('[data-cb-danger]')?.textContent).toContain('may skip permission prompts');
        unmount(handle);
    });

    test('an unrecognized flag gets the warn tone, a known-safe one stays quiet', () => {
        const { target, handle } = render([profileRow([
            { kind: 'flags', text: '--brand-new-option x', tone: 'unknown' },
            { kind: 'flags', text: '--verbose' },
        ])]);
        const row = target.querySelector('[data-cb-command="launch_profiles:0"]')!;
        expect(row.querySelectorAll('[data-cb-unknown]')).toHaveLength(1);
        const unknown = row.querySelector('[data-cb-unknown]')!;
        expect(unknown.textContent).toContain('this flag is not recognized and may change what the agent can do');
        expect(unknown.getAttribute('data-tone')).toBe('warn');
        expect(row.querySelector('[data-cb-danger]')).toBeNull();
        unmount(handle);
    });

    test('a resume command part is named in words, not by its raw kind', () => {
        const { target, handle } = render([profileRow([{ kind: 'resume_command', text: 'aider --resume {id}' }])]);
        const row = target.querySelector('[data-cb-command="launch_profiles:0"]')!;
        expect(row.textContent).toContain('resume command');
        expect(row.textContent).not.toContain('resume_command');
        expect(row.textContent).toContain('aider --resume {id}');
        unmount(handle);
    });

    test('a profile that keeps prompts carries no warning, and markup in a value stays text', () => {
        const { target, handle } = render([profileRow([
            { kind: 'endpoint', value: 'connection', text: '<img src=x>' },
        ])]);
        const row = target.querySelector('[data-cb-command="launch_profiles:0"]')!;
        expect(row.querySelector('[data-cb-danger]')).toBeNull();
        expect(row.querySelector('img')).toBeNull();
        expect(row.textContent).toContain('model endpoint');
        expect(row.textContent).toContain('ai connection');
        expect(row.textContent).toContain('<img src=x>');
        unmount(handle);
    });
});
