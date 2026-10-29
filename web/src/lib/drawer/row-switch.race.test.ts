/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, expect, test } from 'vitest';
import { activateRow } from './row-switch';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const win = window as unknown as Record<string, any>;

interface Deferred { promise: Promise<unknown>; resolve(v: unknown): void }
let fetches: Map<string, Deferred>;
let entered: string[];

function deferred(): Deferred {
    let resolve!: (v: unknown) => void;
    const promise = new Promise<unknown>((r) => { resolve = r; });
    return { promise, resolve };
}

function rowFor(name: string, id: string): HTMLElement {
    const el = document.createElement('div');
    el.className = 'session-sidebar-row';
    el.dataset.name = name;
    el.dataset.sessionId = id;
    return el;
}

const ctrl = { listEl: null, _activeTmuxName: null, _pendingSelection: null, _lastSig: null, _closeAfterSwitch() {}, async _fetchAndRender() {} };

beforeEach(() => {
    entered = [];
    fetches = new Map();
    const log = console.log;
    console.log = () => {};
    new Function(fs.readFileSync(path.join(repoRoot, 'client', 'js', 'navigation-generation.js'), 'utf8'))();
    console.log = log;
    win.CloudeTerminal = { SCROLLBACK_ROWS: 5000 };
    win.API = { getSession: (id: string) => { const d = deferred(); fetches.set(id, d); return d.promise; } };
    win.App = { returnToExistingTerminal: (info: any) => { entered.push(info.session.id); } };
});

afterEach(() => { for (const n of ['NavigationGeneration', 'CloudeTerminal', 'API', 'App']) delete win[n]; });

test('POSITIVE CONTROL: one click, resolved in order, enters that session', async () => {
    const run = activateRow(ctrl as never, rowFor('cloude_a', 'ses_a'));
    fetches.get('ses_a')!.resolve({ session: { id: 'ses_a' } });
    await run;
    expect(entered).toEqual(['ses_a']);
});

test('THE DECISIVE CASE: A resolving after B was clicked paints nothing', async () => {
    const runA = activateRow(ctrl as never, rowFor('cloude_a', 'ses_a'));
    const runB = activateRow(ctrl as never, rowFor('cloude_b', 'ses_b'));
    fetches.get('ses_b')!.resolve({ session: { id: 'ses_b' } });
    await runB;
    fetches.get('ses_a')!.resolve({ session: { id: 'ses_a' } });
    await runA;
    expect(entered).toEqual(['ses_b']);
});

test('the LAST click wins even when it answers first', async () => {
    const runA = activateRow(ctrl as never, rowFor('cloude_a', 'ses_a'));
    const runB = activateRow(ctrl as never, rowFor('cloude_b', 'ses_b'));
    fetches.get('ses_a')!.resolve({ session: { id: 'ses_a' } });
    await runA;
    fetches.get('ses_b')!.resolve({ session: { id: 'ses_b' } });
    await runB;
    expect(entered).toEqual(['ses_b']);
});

test('a click, a return to the same session, and the first is still refused', async () => {
    const runA1 = activateRow(ctrl as never, rowFor('cloude_a', 'ses_a'));
    const runB = activateRow(ctrl as never, rowFor('cloude_b', 'ses_b'));
    fetches.get('ses_b')!.resolve({ session: { id: 'ses_b' } });
    await runB;
    const runA2 = activateRow(ctrl as never, rowFor('cloude_a', 'ses_a2'));
    fetches.get('ses_a2')!.resolve({ session: { id: 'ses_a' } });
    await runA2;
    fetches.get('ses_a')!.resolve({ session: { id: 'ses_a_stale' } });
    await runA1;
    expect(entered).toEqual(['ses_b', 'ses_a']);
});
