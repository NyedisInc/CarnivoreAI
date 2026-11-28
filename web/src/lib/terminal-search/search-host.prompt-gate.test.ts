/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { browserSearchHost } from './search-host';
import type { PromptScanApi } from './types';

const api: PromptScanApi = { scan: () => [], layoutTicks: () => [], currentOrdinalFor: () => 0 };
const win = window as unknown as Record<string, unknown>;

afterEach(() => {
    delete win.TerminalPromptScan;
    delete win.ListingPush;
});

function hostFor(session: Record<string, unknown> | null) {
    win.TerminalPromptScan = api;
    return browserSearchHost({ _currentSession: session } as never);
}

test('claude pane is scanned', () => {
    expect(hostFor({ id: 'a', agent_family: 'claude' }).promptScan()).toBe(api);
});

test('codex pane is scanned with its family bound in (issue #631)', () => {
    const seen: unknown[] = [];
    win.TerminalPromptScan = { ...api, scan: (_b: unknown, o: unknown) => (seen.push(o), []) };
    const scanner = browserSearchHost({ _currentSession: { id: 'a', agent_family: 'codex' } } as never).promptScan();
    scanner?.scan({} as never, { cols: 80 });
    expect(seen).toEqual([{ cols: 80, family: 'codex' }]);
});

test('shell and unknown panes get no scan', () => {
    expect(hostFor({ id: 'a', agent_family: 'shell' }).promptScan()).toBeNull();
    expect(hostFor({ id: 'a' }).promptScan()).toBeNull();
    expect(hostFor(null).promptScan()).toBeNull();
});

test('a bare Session takes its family from the pushed listing wrapper', () => {
    win.ListingPush = { rows: () => [
        { session: { id: 'a' }, agent_family: 'claude' },
        { session: { id: 'b' }, agent_family: 'shell' },
    ] };
    expect(hostFor({ id: 'a' }).promptScan()).toBe(api);
    expect(hostFor({ id: 'b' }).promptScan()).toBeNull();
});

test('an antigravity pane (custom family, agent_type antigravity) is scanned with family agy (issue #3178)', () => {
    const seen: unknown[] = [];
    win.TerminalPromptScan = { ...api, scan: (_b: unknown, o: unknown) => (seen.push(o), []) };
    const session = { id: 'a', agent_family: 'custom', agent_type: 'antigravity' };
    browserSearchHost({ _currentSession: session } as never).promptScan()?.scan({} as never, { cols: 80 });
    expect(seen).toEqual([{ cols: 80, family: 'agy' }]);
    expect(hostFor({ id: 'a', agent_family: 'custom', agent_type: 'other' }).promptScan()).toBeNull();
    seen.length = 0;
    win.TerminalPromptScan = { ...api, scan: (_b: unknown, o: unknown) => (seen.push(o), []) };
    browserSearchHost({ _currentSession: { id: 'c', agent_family: 'custom', agent_type: 'copilot' } } as never).promptScan()?.scan({} as never, { cols: 80 });
    expect(seen).toEqual([{ cols: 80, family: 'copilot' }]);
});
