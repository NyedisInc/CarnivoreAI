import { describe, expect, it } from 'vitest';
import type { ConnectionOption, LaunchProfile } from './api';
import {
    AGENT_PRESETS, TEMPLATES, blankForm, formToProfile, lintMissingArgs, parseFlags, postureSupported, profileToForm, slugFromLabel, templateForm, uniqueId,
} from './form-model';

const conn = (id: string, preset: string, enabled = true): ConnectionOption => ({ id, preset, label: id, enabled, has_key: true, key_hint: 'abcd' });

describe('the "$@" lint', () => {
    it('warns when a script neither forwards "$@" nor names an entry', () => {
        expect(lintMissingArgs('claude --foo', '')).toBe(true);
    });
    it('is quiet when "$@" is forwarded, an entry is named, or there is no script yet', () => {
        expect(lintMissingArgs('claude "$@"', '')).toBe(false);
        expect(lintMissingArgs('claude', 'claude')).toBe(false);
        expect(lintMissingArgs('  ', '')).toBe(false);
    });
});

describe('form to API mapping', () => {
    it('maps a structured claude form field for field', () => {
        const f = { ...blankForm(), id: ' cl ', label: ' cl ', permissions: 'skip_all' as const, modelMode: 'fixed' as const, modelValue: 'm-1', flagsText: '--foo\n\n bar \n', env: [{ name: 'A', value: '1' }, { name: ' ', value: 'x' }] };
        const p = formToProfile(f);
        expect(p).toMatchObject({ id: 'cl', label: 'cl', harness: 'claude', permissions: 'skip_all', model: { mode: 'fixed', value: 'm-1' }, flags: ['--foo', 'bar'], env: [{ name: 'A', value: '1' }], custom_command: null, custom_command_ack_no_args: false });
        expect(p.account).toEqual({ mode: 'follow_active', account_id: null });
    });
    it('clears what the harness cannot use: a posture, a pin, a fixed shell model', () => {
        const codex = formToProfile({ ...blankForm(), id: 'c', label: 'c', harness: 'codex', permissions: 'accept_edits', accountMode: 'pinned', accountId: 'x' });
        expect(codex.permissions).toBe('harness_default');
        expect(codex.account.mode).toBe('follow_active');
        const shell = formToProfile({ ...blankForm(), id: 's', label: 's', harness: 'shell', modelMode: 'fixed', modelValue: 'm', endpointMode: 'connection', connectionId: 'k' });
        expect(shell.model).toEqual({ mode: 'default', value: null });
        expect(shell.endpoint.mode).toBe('native');
    });
    it('sends the custom command and its acknowledgement only in expert mode', () => {
        const base = { ...blankForm(), id: 'x', label: 'x', script: 'claude', ackNoArgs: true };
        expect(formToProfile(base).custom_command).toBeNull();
        const expert = formToProfile({ ...base, expert: true, entry: ' go ' });
        expect(expert.custom_command).toEqual({ script: 'claude', entry: 'go' });
        expect(expert.custom_command_ack_no_args).toBe(true);
    });
    it('round-trips a stored profile', () => {
        const stored: LaunchProfile = {
            id: 'r', harness: 'claude', label: 'r', icon: null, description: 'd', default: false,
            account: { mode: 'follow_active', account_id: null }, endpoint: { mode: 'connection', connection_id: 'k' }, model: { mode: 'ask', value: null },
            permissions: 'ask', flags: ['--x'], env: [{ name: 'A', value: '1' }], secrets: [{ name: 'X_API_KEY', keychain_ref: 'k' }],
            shell_profile: false, before_launch: 'echo', custom_command: null, custom_command_ack_no_args: false,
        };
        expect(formToProfile(profileToForm(stored))).toEqual(stored);
    });
});

describe('postures and ids', () => {
    it('disables the postures a harness lacks', () => {
        expect(postureSupported('codex', 'accept_edits')).toBe(false);
        expect(postureSupported('codex', 'skip_all')).toBe(true);
        expect(postureSupported('shell', 'ask')).toBe(false);
        expect(postureSupported('claude', 'accept_edits')).toBe(true);
    });
    it('slugs a label and keeps ids unique', () => {
        expect(slugFromLabel('Claude via OpenRouter!')).toBe('claude-via-openrouter');
        expect(uniqueId('a', new Set(['a', 'a-2']))).toBe('a-3');
    });
    it('parses one flag per line', () => { expect(parseFlags('a\n\n b ')).toEqual(['a', 'b']); });
});

describe('templates', () => {
    it('picks the matching enabled connection for the endpoint templates, and none when there is none', () => {
        const or = TEMPLATES.find((x) => x.id === 'claude_openrouter')!;
        expect(templateForm(or, 'l', [conn('lm', 'lmstudio'), conn('or1', 'openrouter')]).connectionId).toBe('or1');
        expect(templateForm(or, 'l', [conn('or1', 'openrouter', false)]).connectionId).toBe('');
        expect(templateForm(or, 'l', []).modelMode).toBe('ask');
    });
    it('prefills codex yolo and shell', () => {
        expect(templateForm(TEMPLATES.find((x) => x.id === 'codex_yolo')!, 'c', [])).toMatchObject({ harness: 'codex', permissions: 'skip_all' });
        expect(templateForm(TEMPLATES.find((x) => x.id === 'shell')!, 's', [])).toMatchObject({ harness: 'shell', shellProfile: false });
    });
});

describe('custom agents (#2593)', () => {
    it('every preset is a template that builds a launchable profile with its binary and no model', () => {
        expect(AGENT_PRESETS.length).toBe(18);
        for (const tpl of TEMPLATES.filter((x) => x.agent && x.agent.binary)) {
            const form = templateForm(tpl, tpl.id, []);
            const p = formToProfile({ ...form, id: tpl.id.replace('preset_', 'p-'), modelMode: 'ask' });
            if (p.harness === 'custom') {
                expect(p.custom_command?.script).toBe(`${tpl.agent!.binary} "$@"`);
                expect(p.model).toEqual({ mode: 'default', value: null });
                expect(p.permissions).toBe('harness_default');
            }
        }
    });
    it('a custom agent keeps its typed command and icon through the form', () => {
        const form = { ...templateForm(TEMPLATES.find((x) => x.id === 'custom_agent')!, 'my agent', []), id: 'my-agent', icon: 'logo-qwen', script: 'my-agent --x "$@"' };
        const p = formToProfile(form);
        expect(p).toMatchObject({ harness: 'custom', icon: 'logo-qwen', custom_command: { script: 'my-agent --x "$@"' } });
        expect(profileToForm(p).script).toBe('my-agent --x "$@"');
    });
});

describe('account pin is not offered', () => {
    it('never sends a pin, even from a form loaded from an old pinned profile', () => {
        const p = formToProfile({ ...blankForm(), id: 'c', label: 'c', harness: 'claude', accountMode: 'pinned', accountId: 'work' });
        expect(p.account).toEqual({ mode: 'follow_active', account_id: null });
    });
});
