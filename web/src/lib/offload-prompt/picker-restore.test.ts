/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Win = Record<string, any>;
const win = window as unknown as Win;
const read = (name: string): string => readFileSync(resolve(process.cwd(), '..', 'client', 'js', name), 'utf8') // vitest runs from web/;

const row = (kind: string): Record<string, unknown> => ({ kind, detail: kind === 'offloaded' ? 'offloaded to the backup vault' : 'resumes', projected_kind: kind, projected_detail: kind });
const preview = (kind: string): Record<string, unknown> => ({
    pane_state: 'dead', wrappers_status: 'ok', unchanged: row(kind), projected: row(kind), options: [{ id: 'claude', label: 'claude', ...row(kind), actionable: kind === 'agent' }],
});

const q = (sel: string): HTMLButtonElement | null => document.querySelector<HTMLButtonElement>(sel);
const until = async (probe: () => unknown): Promise<void> => {
    for (let i = 0; i < 50 && !probe(); i += 1) await new Promise((r) => setTimeout(r, 0));
    expect(probe()).toBeTruthy();
};

let prompt: ReturnType<typeof vi.fn>;
let canRestore: ReturnType<typeof vi.fn>;

beforeEach(() => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
    win.CloudeI18n = { t: (key: string) => key };
    (0, eval)(read('i18n/tr.js'));
    prompt = vi.fn(async () => true);
    canRestore = vi.fn(async () => true);
    win.CloudeWeb = { offloadPrompt: { prompt, canRestore } };
    (0, eval)(read('session-restart-options.js'));
    (0, eval)(read('session-restart-picker.js'));
});
afterEach(() => {
    document.body.innerHTML = '';
    for (const k of ['CloudeI18n', 'CloudeTr', 'CloudeWeb', 'SessionRestartOptions', 'SessionRestartPicker']) delete win[k];
    vi.restoreAllMocks();
});

describe('the restart picker with an offloaded conversation', () => {
    it('offers restore when every row is offloaded, and restore opens the prompt and settles so the picker is asked again', async () => {
        const settled = win.SessionRestartPicker.present('build', preview('offloaded'), null, 'recreate', 'S1', false, false, false, null);
        await until(() => q('#restart-picker-restore'));
        expect(q('#restart-picker-restore')!.className).toContain('modal-btn-confirm');
        expect(document.body.textContent).not.toMatch(/start fresh/i);
        q('#restart-picker-restore')!.click();
        const answer = await settled;
        expect(prompt).toHaveBeenCalledTimes(1);
        expect(prompt).toHaveBeenCalledWith({ sessionUuid: 'S1', label: 'build' });
        expect(answer).toEqual({ restored: true });
        expect(q('#restart-picker-dialog')).toBeNull();
    });

    it('offers restore for a MIXED set (some rows offloaded, the others restartable) and restore draws the picker again (#2867)', async () => {
        const mixed = { ...preview('offloaded'), options: [{ id: 'claude', label: 'claude', ...row('agent'), actionable: true }, { id: 'old', label: 'old', ...row('offloaded'), actionable: false }] };
        const settled = win.SessionRestartPicker.present('build', mixed, null, 'recreate', 'S1', false, false, false, null);
        await until(() => q('#restart-picker-restore'));
        q('#restart-picker-restore')!.click();
        expect(await settled).toEqual({ restored: true });
        expect(prompt).toHaveBeenCalledWith({ sessionUuid: 'S1', label: 'build' });
    });

    it('offers no restore when no row is offloaded, mixed or not (#2867)', async () => {
        const plain = { ...preview('agent'), options: [{ id: 'claude', label: 'claude', ...row('agent'), actionable: true }, { id: 'x', label: 'x', ...row('shell'), actionable: false }] };
        void win.SessionRestartPicker.present('build', plain, null, 'recreate', 'S1', false, false, false, null);
        await until(() => q('#restart-picker-dialog'));
        await new Promise((r) => setTimeout(r, 0));
        expect(q('#restart-picker-restore')).toBeNull();
    });

    it('a declined prompt leaves the picker open and settles nothing', async () => {
        prompt.mockResolvedValue(false);
        const settled = vi.fn();
        void win.SessionRestartPicker.present('build', preview('offloaded'), null, 'recreate', 'S1', false, false, false, null).then(settled);
        await until(() => q('#restart-picker-restore'));
        q('#restart-picker-restore')!.click();
        await until(() => prompt.mock.calls.length === 1);
        await new Promise((r) => setTimeout(r, 0));
        expect(settled).not.toHaveBeenCalled();
        expect(q('#restart-picker-dialog')).not.toBeNull();
    });

    it('offers no restore for an ordinary preview, or when the row has no durable id', async () => {
        void win.SessionRestartPicker.present('build', preview('agent'), null, 'recreate', 'S1', false, false, false, null);
        await until(() => q('#restart-picker-dialog'));
        expect(q('#restart-picker-restore')).toBeNull();
        q('#restart-picker-cancel')!.click();
        void win.SessionRestartPicker.present('build', preview('offloaded'), null, 'restart', null, false, false, false, null);
        await until(() => q('#restart-picker-dialog'));
        expect(q('#restart-picker-restore')).toBeNull();
    });

    it('offers no restore while conversation backups are off (the seam says it cannot restore)', async () => {
        canRestore.mockResolvedValue(false);
        void win.SessionRestartPicker.present('build', preview('offloaded'), null, 'recreate', 'S1', false, false, false, null);
        await until(() => q('#restart-picker-dialog'));
        await until(() => canRestore.mock.calls.length === 1);
        await new Promise((r) => setTimeout(r, 0));
        expect(canRestore).toHaveBeenCalledWith({ sessionUuid: 'S1' });
        expect(q('#restart-picker-restore')).toBeNull();
    });

    it('open() draws the picker again after a restore, with a fresh prediction', async () => {
        const previews = [preview('offloaded'), preview('agent')];
        const previewFor = vi.fn(async () => ({ preview: previews.shift(), mode: 'recreate', sessionUuid: 'S1' }));
        win.SessionRestartOptions.previewFor = previewFor;
        win.SessionRestartOptions.accountsFor = async () => null;
        const settled = win.SessionRestartPicker.open('carnivore_a', 'build', null, 'S1');
        await until(() => q('#restart-picker-restore'));
        q('#restart-picker-restore')!.click();
        await until(() => previewFor.mock.calls.length === 2 && q('#restart-picker-dialog') && !q('#restart-picker-restore'));
        q('#restart-picker-cancel')!.click();
        expect(await settled).toBeNull();
    });
});
