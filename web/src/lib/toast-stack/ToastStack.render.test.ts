/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import { mountPanel, unmountPanel } from '../mount';
import ToastStack from './ToastStack.svelte';

const muteAttach = vi.hoisted(() => vi.fn());
vi.mock('../notifications/mute/mute-control', () => ({ attach: muteAttach }));

const LEGACY = path.resolve(__dirname, '../../../../client/js');
const read = (file: string): string => fs.readFileSync(path.join(LEGACY, file), 'utf8');

type Loose = Record<string, unknown>;
type Manager = {
  add(toast: Loose): void;
  updateLocal(id: string, patch: Loose): boolean;
  dismiss(id: string, opts?: { syncToServer?: boolean }): void;
  dismissAll(): number;
  _view: { cards: Loose[] };
};
const win = window as unknown as Loose & { ToastManager: Manager };

let seq = 0;
function toast(kind: string, title: string, body: string | null = null, session = 's1', sessionName: string | null = null, extra: Loose = {}): Loose {
  seq += 1;
  return { id: `t${seq}`, session_id: session, session_name: sessionName, kind, title, body, color: '#ff8800', acknowledged: false, ...extra };
}

let acked: string[] = [];
let narrow = false;

function loadLegacy(): void {
  const indirectEval = eval;
  for (const file of ['session-label.js', 'session-status-summary.js', 'toast-session-group.js', 'toast-version-arbitration.js']) indirectEval(read(file));
  indirectEval(['toast.js', 'toast-grouping.js', 'toast-view.js', 'toast-lifecycle.js'].map(read).join('\n;\n'));
}

beforeEach(() => {
  seq = 0;
  acked = [];
  narrow = false;
  vi.useFakeTimers();
  vi.spyOn(console, 'log').mockImplementation(() => undefined);
  vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  muteAttach.mockReset();
  document.body.innerHTML = '<div id="toast-container" class="toast-container" data-oc-base aria-live="polite"></div>';
  const query = { get matches() { return narrow; }, addEventListener: () => undefined };
  window.matchMedia = (() => query) as unknown as typeof window.matchMedia;
  win.API = { ackToast: (id: string) => { acked.push(id); return Promise.resolve(); } };
  loadLegacy();
  mountPanel('toast-container', ToastStack, {});
  flushSync();
});

afterEach(() => {
  unmountPanel('toast-container');
  vi.useRealTimers();
  vi.restoreAllMocks();
  for (const key of ['ToastManager', 'API', 'ToastNavigate', 'ToastMode', 'SessionRowMenuIcons', 'ToastSessionGroup', 'SessionStatusSummary', 'ToastVersionArbitration', 'SessionLabel']) {
    delete win[key];
  }
});

const mgr = (): Manager => win.ToastManager;
const stack = (): HTMLElement => document.getElementById('toast-container') as HTMLElement;
const cards = (): HTMLElement[] => Array.from(stack().querySelectorAll<HTMLElement>(':scope > .toast'));
function nth<T>(list: ArrayLike<T>, i: number): T {
  const found = list[i];
  if (found === undefined) throw new Error(`expected an element at index ${i}, the list holds ${list.length}`);
  return found;
}
const at = (i = 0): HTMLElement => nth(cards(), i);
const text = (el: Element | null): string => el?.textContent?.trim() ?? '';
function show(...records: Loose[]): void {
  for (const r of records) mgr().add(r);
  flushSync();
}

describe('a toast shown through ToastManager paints a Svelte card', () => {
  it('paints the title, the session line, the body and the x, inside the page container', () => {
    show(toast('Notification', 'claude is waiting', 'needs a file path', 'ses_1', 'cloude_proj'));
    const card = at(0);
    expect(card).toBeTruthy();
    expect(card.parentElement).toBe(stack());
    expect(card.dataset.kind).toBe('Notification');
    expect(text(card.querySelector('.toast__title-text'))).toBe('claude is waiting');
    expect(text(card.querySelector('.toast__body'))).toBe('needs a file path');
    expect(card.querySelector('.toast__session')?.tagName).toBe('BUTTON');
    expect(card.querySelector('.toast__dismiss')?.getAttribute('aria-label')).toBe('dismiss notification');
  });

  it('is painted by the Svelte stack and by nothing else: unmounted, the manager adds no node', () => {
    unmountPanel('toast-container');
    flushSync();
    mgr().add(toast('Stop', 'Your turn'));
    expect(stack().children).toHaveLength(0);
    expect(mgr()._view.cards).toHaveLength(1);
    mountPanel('toast-container', ToastStack, {});
    flushSync();
    expect(cards()).toHaveLength(1);
  });

  it('draws nothing for an empty model (a stack that looked at nothing is not a pass)', () => {
    expect(cards()).toHaveLength(0);
    show(toast('Stop', 'Your turn'));
    expect(cards()).toHaveLength(1);
  });

  it('carries the session accent and role: alert only for a blocking prompt', () => {
    show(toast('PermissionRequest', 'permission needed', 'Bash: ls', 'A', null, { color: '#d7788c' }), toast('Stop', 'Your turn', null, 'B'));
    const perm = at(0);
    const stop = at(1);
    expect(perm.getAttribute('role')).toBe('alert');
    expect(perm.dataset.themed).toBe('1');
    expect(perm.style.getPropertyValue('--toast-accent')).toBe('#d7788c');
    expect(stop.getAttribute('role')).toBe('status');
  });
});

describe('stacking: one card per session, the cap, the overflow row', () => {
  it('coalesces twelve Stops into one card with a x12 badge', () => {
    for (let i = 0; i < 12; i += 1) mgr().add(toast('Stop', 'Your turn', `tail ${i}`));
    flushSync();
    expect(cards()).toHaveLength(1);
    expect(text(at(0).querySelector('.toast__count'))).toBe('×12');
    expect(at(0).querySelector('.toast__count')?.getAttribute('aria-label')).toBe('12 occurrences');
    expect(text(at(0).querySelector('.toast__body'))).toBe('tail 11');
  });

  it('caps at three on desktop, holds the rest behind a row that tells the truth, and expands on click', () => {
    for (let i = 0; i < 12; i += 1) mgr().add(toast('Notification', 'claude is waiting', `m${i}`, `ses_${i}`));
    flushSync();
    expect(cards()).toHaveLength(3);
    const row = stack().querySelector<HTMLElement>('.toast-overflow') as HTMLElement;
    expect(row.dataset.hiddenCount).toBe('9');
    expect(text(row)).toContain('+9 more');
    expect(text(row)).toContain('(9 waiting on you)');
    expect(stack().lastElementChild).toBe(row);
    row.click();
    flushSync();
    expect(cards()).toHaveLength(12);
    expect(text(stack().querySelector('.toast-overflow'))).toBe('show fewer');
    expect(stack().querySelector('.toast-overflow')?.getAttribute('aria-expanded')).toBe('true');
  });

  it('never hides a blocking prompt behind the row, and sorts it to the top', () => {
    for (let i = 0; i < 10; i += 1) mgr().add(toast('Notification', 'claude is waiting', `m${i}`, `ses_${i}`));
    mgr().add(toast('PermissionRequest', 'permission needed', 'rm -rf', 'ses_99'));
    flushSync();
    expect(at(0).dataset.kind).toBe('PermissionRequest');
    expect(stack().querySelector<HTMLElement>('.toast-overflow')?.dataset.worstSeverity).toBe('2');
  });

  it('caps at two on a phone', () => {
    narrow = true;
    for (let i = 0; i < 8; i += 1) mgr().add(toast('Notification', 'claude is waiting', `m${i}`, `ses_${i}`));
    flushSync();
    expect(cards()).toHaveLength(2);
    expect(stack().querySelector<HTMLElement>('.toast-overflow')?.dataset.hiddenCount).toBe('6');
  });

  it('keeps the same element for a group across a re-render (no restarted entry animation)', () => {
    show(toast('Stop', 'Your turn', 'first'));
    const before = at(0);
    show(toast('PermissionRequest', 'permission needed', 'Bash: rm', 's1'));
    expect(cards()).toHaveLength(1);
    expect(at(0)).toBe(before);
    expect(before.dataset.kind).toBe('PermissionRequest');
    expect(before.getAttribute('role')).toBe('alert');
  });
});

describe('dismissing', () => {
  it('shows "Dismiss all" only for two or more cards, first in the stack, and names the blocking ones', () => {
    show(toast('Stop', 'Your turn', null, 'A'));
    expect(stack().querySelector('.toast-dismiss-all')).toBeNull();
    show(toast('PermissionRequest', 'permission needed', null, 'B'));
    const all = stack().querySelector<HTMLElement>('.toast-dismiss-all') as HTMLElement;
    expect(stack().firstElementChild).toBe(all);
    expect(text(all)).toBe('dismiss all (2)');
    expect(all.getAttribute('aria-label')).toBe('dismiss all 2 notifications, including 1 waiting on your permission');
    expect(all.dataset.blocking).toBe('1');
    all.click();
    flushSync();
    expect(acked.sort()).toEqual(['t1', 't2']);
    vi.advanceTimersByTime(300);
    flushSync();
    expect(cards()).toHaveLength(0);
    expect(stack().querySelector('.toast-dismiss-all')).toBeNull();
  });

  it('the x fades the card, acks EVERY member, and the card leaves after the fade', () => {
    const made = [toast('Stop', 'Your turn', 'a'), toast('Stop', 'Your turn', 'b'), toast('Stop', 'Your turn', 'c')];
    show(...made);
    vi.advanceTimersByTime(50);
    flushSync();
    const card = at(0);
    expect(card.querySelector('.toast__dismiss')?.getAttribute('aria-label')).toBe('dismiss 3 notifications for this session');
    (card.querySelector('.toast__dismiss') as HTMLElement).click();
    flushSync();
    expect(at(0)).toBe(card);
    expect(card.classList.contains('toast--dismissing')).toBe(true);
    expect(card.classList.contains('toast--entering')).toBe(false);
    expect(acked.sort()).toEqual(made.map((m) => m.id as string).sort());
    expect(cards()).toHaveLength(1);
    expect(at(0).classList.contains('toast--dismissing')).toBe(true);
    vi.advanceTimersByTime(219);
    flushSync();
    expect(cards()).toHaveLength(1);
    vi.advanceTimersByTime(2);
    flushSync();
    expect(cards()).toHaveLength(0);
  });

  it('a toast arriving mid-fade gets its OWN card, never the corpse of the dismissed one', () => {
    show(toast('Stop', 'Your turn', 'first'));
    (at(0).querySelector('.toast__dismiss') as HTMLElement).click();
    flushSync();
    const corpse = at(0);
    show(toast('Stop', 'Your turn', 'second'));
    expect(corpse.isConnected).toBe(true);
    expect(corpse.classList.contains('toast--dismissing')).toBe(true);
    const live = cards().filter((c) => !c.classList.contains('toast--dismissing'));
    expect(live).toHaveLength(1);
    expect(nth(live, 0)).not.toBe(corpse);
    expect(text(nth(live, 0).querySelector('.toast__body'))).toBe('second');
    expect(nth(live, 0).querySelector('.toast__count')).toBeNull();
  });

  it('a middle click dismisses by the same teardown and opens nothing; mousedown 1 is cancelled, 0 is not', () => {
    const open = vi.fn();
    win.ToastNavigate = { open, isAskToast: () => false };
    show(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    const card = at(0);
    expect(card.dispatchEvent(new MouseEvent('mousedown', { button: 1, bubbles: true, cancelable: true }))).toBe(false);
    expect(card.dispatchEvent(new MouseEvent('mousedown', { button: 0, bubbles: true, cancelable: true }))).toBe(true);
    card.dispatchEvent(new MouseEvent('auxclick', { button: 1, bubbles: true, cancelable: true }));
    flushSync();
    expect(acked).toEqual(['t1']);
    expect(open).not.toHaveBeenCalled();
  });
});

describe('clicks', () => {
  it('clicking the card opens its session once; Enter and Space do the same', () => {
    const open = vi.fn();
    win.ToastNavigate = { open, isAskToast: () => false };
    show(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    const card = at(0);
    expect(card.classList.contains('toast--clickable')).toBe(true);
    expect(card.getAttribute('tabindex')).toBe('0');
    card.click();
    expect(open).toHaveBeenCalledTimes(1);
    card.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    card.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true }));
    expect(open).toHaveBeenCalledTimes(3);
    expect(acked).toEqual([]);
  });

  it('Enter or Space on a button inside the card presses that button and does not open the session', () => {
    const open = vi.fn();
    win.ToastNavigate = { open, isAskToast: () => false };
    show(toast('Notification', 'claude is waiting', 'a body', 'A', 'cloude_a'));
    for (const sel of ['.toast__toggle', '.toast__dismiss', '.toast__session']) {
      const inner = at(0).querySelector(sel) as HTMLElement;
      for (const key of ['Enter', ' ']) {
        const evt = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
        inner.dispatchEvent(evt);
        expect(evt.defaultPrevented).toBe(false);
      }
    }
    expect(open).not.toHaveBeenCalled();
  });

  it('clicking the session NAME navigates EXACTLY ONCE and dismisses the card (the bubble is the open)', () => {
    const open = vi.fn();
    win.ToastNavigate = { open, isAskToast: () => false };
    show(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    (at(0).querySelector('.toast__session') as HTMLElement).click();
    flushSync();
    expect(open).toHaveBeenCalledTimes(1);
    expect(acked).toEqual(['t1']);
  });

  it('the x never navigates', () => {
    const open = vi.fn();
    win.ToastNavigate = { open, isAskToast: () => false };
    show(toast('Stop', 'Your turn', null, 'A', 'cloude_a'));
    (at(0).querySelector('.toast__dismiss') as HTMLElement).click();
    expect(open).not.toHaveBeenCalled();
    expect(acked).toEqual(['t1']);
  });

  it('an ask (question or permission) opens the approvals popup and the card goes', () => {
    const open = vi.fn();
    win.ToastNavigate = { open, isAskToast: (t: Loose) => t.kind === 'PermissionRequest' };
    show(toast('PermissionRequest', 'permission needed', null, 'A', 'cloude_a'));
    at(0).click();
    flushSync();
    expect(open).toHaveBeenCalledTimes(1);
    expect(acked).toEqual(['t1']);
  });

  it('a card with no session to go to is not clickable', () => {
    show(toast('Stop', 'Your turn', null, null as unknown as string));
    expect(at(0).classList.contains('toast--clickable')).toBe(false);
    expect(at(0).getAttribute('tabindex')).toBeNull();
    expect(at(0).querySelector('.toast__session')?.tagName).toBe('DIV');
    expect(at(0).querySelector<HTMLElement>('.toast__session')?.dataset.unknown).toBe('1');
    expect(text(at(0).querySelector('.toast__session'))).toBe('unknown session');
  });

  it('a local card runs its one action once and retires; a server card draws no button; the click is not the card', () => {
    const ran = vi.fn();
    const open = vi.fn();
    show(
      toast('WidgetsBars', 'added', null, null as unknown as string, null, { id: 'loc1', local: true, action_label: 'undo', on_action: ran, on_open: open }),
      toast('Stop', 'done', null, 's9', null, { action_label: 'undo', on_action: ran }),
    );
    const withAction = cards().filter((c) => c.querySelector('.toast__action'));
    expect(withAction).toHaveLength(1);
    (nth(withAction, 0).querySelector('.toast__action') as HTMLElement).click();
    flushSync();
    expect(ran).toHaveBeenCalledTimes(1);
    expect(open).not.toHaveBeenCalled();
    expect(acked).toEqual([]);
    vi.advanceTimersByTime(300);
    flushSync();
    expect(cards().some((c) => c.dataset.toastId === 'loc1')).toBe(false);
  });

  it('a local card with on_open runs it and retires the card', () => {
    const open = vi.fn();
    show(toast('AppAlert', 'alert', null, null as unknown as string, null, { id: 'a1', local: true, on_open: open }));
    at(0).click();
    expect(open).toHaveBeenCalledTimes(1);
  });
});

describe('the phone collapse toggle', () => {
  it('a card with a body gets it, with show/hide labels that flip with aria-expanded and data-expanded', () => {
    show(toast('Notification', 'claude is waiting', 'a body'));
    const card = at(0);
    const toggle = card.querySelector<HTMLElement>('.toast__toggle') as HTMLElement;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.getAttribute('aria-label')).toBe('show full notification');
    expect(card.dataset.expanded).toBeUndefined();
    toggle.click();
    flushSync();
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(toggle.getAttribute('aria-label')).toBe('hide full notification');
    expect(toggle.getAttribute('title')).toBe('hide full notification');
    expect(card.dataset.expanded).toBe('1');
    toggle.click();
    flushSync();
    expect(card.dataset.expanded).toBe('0');
  });

  it('survives a re-render of the same group, and does not also navigate', () => {
    const open = vi.fn();
    win.ToastNavigate = { open, isAskToast: () => false };
    show(toast('Notification', 'claude is waiting', 'a body', 'A', 'cloude_a'));
    (at(0).querySelector('.toast__toggle') as HTMLElement).click();
    flushSync();
    show(toast('Notification', 'claude is waiting', 'newer body', 'A', 'cloude_a'));
    expect(at(0).dataset.expanded).toBe('1');
    expect(open).not.toHaveBeenCalled();
  });

  it('a card with neither a body nor the Attachment kind gets no toggle; an attachment with no body does', () => {
    show(toast('Stop', 'Your turn', null, 'A'));
    expect(at(0).querySelector('.toast__toggle')).toBeNull();
    show(toast('Attachment', 'attached', null, 'B', null, { local: true, attachment_name: 'a.pdf', thumb_label: 'PDF', thumb_url: null }));
    const attach = cards().find((c) => c.dataset.kind === 'Attachment') as HTMLElement;
    expect(attach.querySelector('.toast__toggle')).not.toBeNull();
  });
});

describe('the attachment strip', () => {
  const attach = (name: string, extra: Loose = {}): Loose => toast('Attachment', 'attached', null, 'A', null, { local: true, attachment_name: name, thumb_label: 'PDF', thumb_url: null, ...extra });

  it('a preview renders an img named after the file; no preview renders a chip and no img', () => {
    show(attach('shot.png', { thumb_url: 'data:image/webp;base64,AA' }), attach('spec.pdf'));
    const strip = at(0).querySelector('.toast__thumbs') as HTMLElement;
    const rows = strip.querySelectorAll('.toast__thumb-row');
    expect(rows).toHaveLength(2);
    const img = strip.querySelector('.toast__thumb-img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('data:image/webp;base64,AA');
    expect(img.getAttribute('alt')).toBe('shot.png');
    expect(strip.querySelectorAll('.toast__thumb-img')).toHaveLength(1);
    const chip = strip.querySelector('.toast__thumb-ext') as HTMLElement;
    expect(chip.textContent).toBe('PDF');
    expect(chip.getAttribute('aria-hidden')).toBe('true');
    expect((chip.parentElement as HTMLElement).dataset.noPreview).toBe('1');
    expect(text(nth(rows, 0).querySelector('.toast__thumb-name'))).toBe('shot.png');
  });

  it('draws every member of the group, and an unnamed file says so', () => {
    show(attach('a.png', { thumb_url: 'data:,1' }), attach('b.pdf'), attach(''));
    expect(cards()).toHaveLength(1);
    expect(at(0).querySelectorAll('.toast__thumb-row')).toHaveLength(3);
    expect(text(nth(at(0).querySelectorAll('.toast__thumb-name'), 2))).toBe('(unnamed file)');
  });

  it('a late preview replaces the chip on the same card, with one strip', () => {
    const t = attach('shot.png');
    show(t);
    expect(at(0).querySelector('.toast__thumb-img')).toBeNull();
    expect(mgr().updateLocal(t.id as string, { thumb_url: 'data:,late' })).toBe(true);
    flushSync();
    expect(at(0).querySelectorAll('.toast__thumbs')).toHaveLength(1);
    expect(at(0).querySelector('.toast__thumb-img')?.getAttribute('src')).toBe('data:,late');
  });

  it('a picture with its blob is a button that opens the full-size overlay and is not the card click', () => {
    const open = vi.fn();
    win.ToastNavigate = { open, isAskToast: () => false };
    show(attach('shot.png', { thumb_url: 'data:,1', full_blob: new Blob(['x'], { type: 'image/png' }), session_name: 'cloude_a' }));
    const btn = at(0).querySelector('.toast__thumb-btn') as HTMLElement;
    expect(btn.getAttribute('aria-label')).toBe('view shot.png full size');
    btn.click();
    expect(open).not.toHaveBeenCalled();
    expect(document.getElementById('attachment-lightbox') ?? document.querySelector('[data-attachment-lightbox]') ?? true).toBeTruthy();
  });
});

describe('kinds and modes', () => {
  it('the auto-sleep title carries the app\'s own moon before the text; no other kind does', () => {
    win.SessionRowMenuIcons = { svg: (name: string, size: number) => `<svg data-glyph="${name}" width="${size}" stroke="currentColor"></svg>` };
    show(toast('AutoSlept', 'session put to sleep', 'slept api', 'A'), toast('Notification', 'claude is waiting', null, 'B'));
    const sleep = cards().find((c) => c.dataset.kind === 'AutoSlept') as HTMLElement;
    const title = sleep.querySelector('.toast__title') as HTMLElement;
    const icon = title.querySelector('.toast__title-icon') as HTMLElement;
    expect(icon.innerHTML).toContain('data-glyph="sleep"');
    expect(icon.innerHTML).toContain('stroke="currentColor"');
    expect(title.firstElementChild).toBe(icon);
    expect(text(title.querySelector('.toast__title-text'))).toBe('session put to sleep');
    expect(cards().find((c) => c.dataset.kind === 'Notification')?.querySelector('.toast__title-icon')).toBeNull();
  });

  it('detailed mode titles from the record\'s facts, shows the snippet, and says "2 sessions waiting"', () => {
    const mode = {
      isDetailed: () => true,
      pickLatest: (list: Loose[]) => ({ winner: list[list.length - 1], count: list.length }),
      headline: (t: Loose) => `detailed: ${String(t.title)}`,
      snippet: (t: Loose) => `snippet of ${String(t.id)}`,
      waitingRowCount: (groups: unknown[]) => (groups.length >= 2 ? groups.length : null),
    };
    win.ToastMode = mode;
    show(toast('Stop', 'Your turn', 'body', 'A'), toast('Notification', 'claude is waiting', 'body', 'B'));
    expect(at(0).dataset.mode).toBe('detailed');
    expect(text(at(0).querySelector('.toast__title-text'))).toMatch(/^detailed: /);
    expect(text(at(0).querySelector('.toast__body'))).toMatch(/^snippet of /);
    const waiting = stack().querySelector<HTMLElement>('.toast-waiting') as HTMLElement;
    expect(waiting.getAttribute('role')).toBe('status');
    expect(text(waiting)).toBe('2 sessions waiting');
    expect(waiting.previousElementSibling).toBe(stack().querySelector('.toast-dismiss-all'));
    expect(waiting.nextElementSibling).toBe(at(0));
  });

  it('an untitled record says so', () => {
    show(toast('Stop', '', null, 'A'));
    expect(text(at(0).querySelector('.toast__title-text'))).toBe('(untitled)');
  });
});

describe('boot order', () => {
  it('mounts the toast stack before the long boot sequence, so a throw later in it cannot leave the page with no toasts', () => {
    const main = fs.readFileSync(path.resolve(__dirname, '../../main.ts'), 'utf8');
    const mount = main.indexOf("mountPanel('toast-container', ToastStack");
    expect(mount).toBeGreaterThan(0);
    for (const later of ['installRowMenuOpener();', 'bootListingPush();', 'startApprovals();', 'startCplugs();', "mountPanel('pack-op-toast-container'"]) {
      expect(main.indexOf(later), later).toBeGreaterThan(mount);
    }
  });
});

describe('the frame and the mute button', () => {
  it('a new card enters with toast--entering and drops it a frame after mount', () => {
    show(toast('Stop', 'Your turn'));
    const card = at(0);
    expect(card.classList.contains('toast--entering')).toBe(true);
    vi.advanceTimersByTime(50);
    flushSync();
    expect(card.classList.contains('toast--entering')).toBe(false);
  });

  it('hands every drawn card to the mute module, which may add its own children and class', () => {
    const attach = muteAttach;
    attach.mockImplementation((card: HTMLElement) => { card.classList.add('toast--mutable'); });
    show(toast('Stop', 'Your turn', null, 'A'));
    expect(attach).toHaveBeenCalled();
    expect(nth(attach.mock.calls, 0)[1]).toMatchObject({ kind: 'Stop' });
    expect(at(0).classList.contains('toast--mutable')).toBe(true);
    show(toast('Stop', 'Your turn', 'again', 'A'));
    expect(at(0).classList.contains('toast--mutable')).toBe(true);
  });

  it('re-attaches only when the winning record changes, so an unrelated toast leaves an open popover alone', () => {
    show(toast('Stop', 'Your turn', null, 'A'));
    const before = muteAttach.mock.calls.length;
    expect(before).toBeGreaterThan(0);
    show(toast('Stop', 'Your turn', null, 'B'));
    flushSync();
    const cardA = cards().find((c) => c.dataset.sessionId === 'A') as HTMLElement;
    const forA = muteAttach.mock.calls.filter(([el]) => el === cardA).length;
    expect(forA).toBe(1);
  });
});
