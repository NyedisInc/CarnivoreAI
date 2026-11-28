/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Win = Record<string, any>;
const win = window as unknown as Win;
const read = (name: string): string => readFileSync(resolve(process.cwd(), '..', 'client', 'js', name), 'utf8'); // vitest runs from web/

const OFFER = { id: 'o1', reason: 'reboot', boot_epoch: 1, created_at: '2026-11-06T10:00:00Z' };
const item = (uuid: string, extra: Record<string, unknown>): Record<string, unknown> => ({
    session_uuid: uuid, title: `s-${uuid}`, tmux_name: `carnivore_${uuid}`, folder: '/a/b', conversation: 'c0nversation', selectable: true, blocked: null,
    wrapper_default: 'claude', wrapper_options: [{ id: 'claude', label: 'claude' }], ...extra,
});
const BLOCKED = item('S1', { selectable: false, blocked: 'offloaded', detail: 'in the vault' });
const FREE = item('S2', {});
const REOPENABLE = item('S1', {});

const until = async (probe: () => unknown): Promise<void> => {
    for (let i = 0; i < 50 && !probe(); i += 1) await new Promise((r) => setTimeout(r, 0));
    expect(probe()).toBeTruthy();
};

let prompt: ReturnType<typeof vi.fn>;
let canRestore: ReturnType<typeof vi.fn>;
let warn: ReturnType<typeof vi.fn>;
let call: ReturnType<typeof vi.fn>;

beforeEach(() => {
    warn = vi.spyOn(console, 'warn').mockImplementation(() => {}) as unknown as ReturnType<typeof vi.fn>;
    win.CloudeI18n = { t: (key: string) => key };
    (0, eval)(read('i18n/tr.js'));
    prompt = vi.fn(async () => true);
    canRestore = vi.fn(async () => true);
    win.CloudeWeb = { offloadPrompt: { prompt, canRestore } };
    (0, eval)(read('session-restore-offer.js'));
    call = vi.fn(async () => ({ offer: OFFER, sessions: [REOPENABLE, FREE] }));
});
afterEach(() => {
    document.body.innerHTML = '';
    for (const k of ['CloudeI18n', 'CloudeTr', 'CloudeWeb', 'SessionRestoreOffer']) delete win[k];
    vi.restoreAllMocks();
});

describe('the reopen offer with an offloaded conversation', () => {
    it('draws a restore button on the offloaded row only, in the modal button family (red when the row has only text)', async () => {
        win.SessionRestoreOffer.render({ call }, OFFER, [BLOCKED, FREE]);
        const buttons = document.querySelectorAll<HTMLButtonElement>('[data-restore-offloaded]');
        expect(buttons).toHaveLength(1);
        await until(() => !buttons[0]!.hidden);
        expect(buttons[0]!.dataset.restoreOffloaded).toBe('S1');
        expect(buttons[0]!.className).toContain('modal-btn');
        expect(buttons[0]!.closest('.restore-offer__row')!.getAttribute('data-session-uuid')).toBe('S1');
    });

    it('restore opens the one prompt for that session, then the offer is asked again and the row is reopenable (red when the row stays blocked)', async () => {
        const api = { call };
        win.SessionRestoreOffer.render(api, OFFER, [BLOCKED, FREE]);
        await until(() => !document.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!.hidden);
        document.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!.click();
        await until(() => call.mock.calls.length === 1);
        expect(prompt).toHaveBeenCalledWith({ sessionUuid: 'S1', label: 's-S1' });
        await until(() => document.querySelector('[data-session-uuid="S1"] .restore-offer__check:not([disabled])'));
        expect(document.querySelector('[data-restore-offloaded]')).toBeNull();
        expect(call).toHaveBeenCalledWith('/sessions/restore-offer');
    });

    it('a declined prompt leaves the row blocked and asks the server nothing (red when the offer redraws as if it restored)', async () => {
        prompt.mockResolvedValue(false);
        win.SessionRestoreOffer.render({ call }, OFFER, [BLOCKED, FREE]);
        await until(() => !document.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!.hidden);
        document.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!.click();
        await until(() => prompt.mock.calls.length === 1);
        await new Promise((r) => setTimeout(r, 0));
        expect(call).not.toHaveBeenCalled();
        expect(document.querySelector('[data-restore-offloaded]')).not.toBeNull();
    });

    it('a row the user unticked stays unticked after a restore; only the newly reopenable row starts ticked (red when the redraw re-ticks everything)', async () => {
        const second = item('S3', {});
        call.mockResolvedValue({ offer: OFFER, sessions: [REOPENABLE, FREE, second] });
        win.SessionRestoreOffer.render({ call }, OFFER, [BLOCKED, FREE, second]);
        await until(() => !document.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!.hidden);
        const tick = (uuid: string): HTMLInputElement => document.querySelector<HTMLInputElement>(`[data-session-uuid="${uuid}"] .restore-offer__check`)!;
        tick('S2').click();
        expect(tick('S2').checked).toBe(false);
        document.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!.click();
        await until(() => call.mock.calls.length === 1 && !document.querySelector('[data-restore-offloaded]'));
        expect(tick('S2').checked).toBe(false);
        expect(tick('S3').checked).toBe(true);
        expect(tick('S1').checked).toBe(true);
    });

    it('hides the restore button while conversation backups are off (red when it is shown regardless)', async () => {
        canRestore.mockResolvedValue(false);
        win.SessionRestoreOffer.render({ call }, OFFER, [BLOCKED, FREE]);
        await until(() => canRestore.mock.calls.length === 1);
        await new Promise((r) => setTimeout(r, 0));
        expect(canRestore).toHaveBeenCalledWith({ sessionUuid: 'S1' });
        expect(document.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!.hidden).toBe(true);
    });

    it('a failed re-read after a good restore says so, not that the restore failed (red when it logs "restore failed")', async () => {
        call.mockRejectedValue(new Error('network'));
        win.SessionRestoreOffer.render({ call }, OFFER, [BLOCKED, FREE]);
        await until(() => !document.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!.hidden);
        document.querySelector<HTMLButtonElement>('[data-restore-offloaded]')!.click();
        await until(() => warn.mock.calls.length >= 1);
        const said = warn.mock.calls.map((c) => String(c[0])).join('|');
        expect(said).toContain('could not be read again');
        expect(said).not.toContain('restore failed');
    });
});
