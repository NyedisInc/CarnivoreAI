/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => ({ ...(await importOriginal<object>()), authFetch }));

import FirstRunAgent from './FirstRunAgent.svelte';
import { parseAgentCheck } from './agent-check-api';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

const report = (claude: 'PASS' | 'FAIL', codex: boolean | null) => ({
    status: claude,
    checks: [
        { name: 'files', status: 'PASS', summary: 'ok', findings: [] },
        { name: 'claude_cli', status: claude, summary: claude === 'PASS' ? 'claude at /x/claude' : 'claude not found', findings: [] },
    ],
    ...(codex === null ? {} : { agents: { codex: { found: codex, path: codex ? '/x/codex' : null } } }),
});

const mounted: ReturnType<typeof mount>[] = [];
const onContinue = vi.fn();
const q = (sel: string) => document.querySelector(sel) as HTMLElement | null;
const settle = async () => {
    for (let i = 0; i < 8; i++) await tick();
    flushSync();
};
async function render() {
    mounted.push(mount(FirstRunAgent, { target: document.body, props: { onContinue } }));
    await settle();
}

beforeEach(() => {
    authFetch.mockReset();
    onContinue.mockReset();
});
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});

describe('parseAgentCheck', () => {
    test('reads claude from the claude_cli check and codex from agents', () => {
        expect(parseAgentCheck(report('PASS', true))).toEqual({ claude: true, codex: true });
        expect(parseAgentCheck(report('FAIL', false))).toEqual({ claude: false, codex: false });
    });
    test('a report with no claude_cli check, or no agents, is not a guess of present', () => {
        expect(parseAgentCheck({ status: 'PASS', checks: [] })).toBeNull();
        expect(parseAgentCheck(report('PASS', null))).toEqual({ claude: true, codex: false });
        expect(parseAgentCheck('nope')).toBeNull();
    });
});

describe('the agent row', () => {
    test('present: says claude code found, shows codex when present, no install help', async () => {
        authFetch.mockResolvedValue(report('PASS', true));
        await render();
        expect(authFetch).toHaveBeenCalledWith('/self-check', expect.anything());
        expect(q('[data-first-run="claude"]')!.textContent).toContain(t('first_run.agent.claude_found'));
        expect(q('[data-first-run="codex"]')!.textContent).toContain(t('first_run.agent.codex_found'));
        expect(q('[data-first-run="agent-install"]')).toBeNull();
        expect(q('[data-first-run="recheck"]')).toBeNull();
    });

    test('missing: names the official install command and the sign in step, offers recheck, hides codex', async () => {
        authFetch.mockResolvedValue(report('FAIL', false));
        await render();
        expect(q('[data-first-run="claude"]')!.textContent).toContain(t('first_run.agent.claude_missing'));
        expect(q('[data-first-run="agent-install"]')!.textContent).toContain(t('first_run.agent.install'));
        expect(q('[data-first-run="install-cmd"]')!.textContent).toContain('curl -fsSL https://claude.ai/install.sh | bash');
        expect(q('[data-first-run="agent-signin"]')!.textContent).toContain(t('first_run.agent.signin'));
        expect(q('[data-first-run="codex"]')).toBeNull();
        expect(q('[data-first-run="recheck"]')).not.toBeNull();
    });

    test('recheck asks again and flips to found', async () => {
        authFetch.mockResolvedValueOnce(report('FAIL', false)).mockResolvedValueOnce(report('PASS', false));
        await render();
        q('[data-first-run="recheck"]')!.click();
        await settle();
        expect(authFetch).toHaveBeenCalledTimes(2);
        expect(q('[data-first-run="claude"]')!.textContent).toContain(t('first_run.agent.claude_found'));
        expect(q('[data-first-run="recheck"]')).toBeNull();
    });

    test('a self-check that cannot answer says so, keeps recheck, and never blocks continue', async () => {
        authFetch.mockRejectedValue(new Error('down'));
        await render();
        expect(q('[data-first-run="claude"]')!.textContent).toContain(t('first_run.agent.unknown'));
        expect(q('[data-first-run="recheck"]')).not.toBeNull();
        q('[data-first-run="agent-continue"]')!.click();
        expect(onContinue).toHaveBeenCalledTimes(1);
    });
});
