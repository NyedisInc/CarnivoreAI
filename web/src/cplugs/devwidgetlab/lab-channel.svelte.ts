import {
  applyIntent, defaultSelection, EMPTY_LIVE, DEFAULT_FOLDS, LAB_CHANNEL, normalizeFolds, normalizeSelection, SELECTION_KEY,
  type LabFolds, type LabIntent, type LabLive, type LabSelection,
} from './lab-selection';
import type { LabWidget } from '../sdk/widget-lab';

export type LabRole = 'menu' | 'viewer';

type Frame =
  | { kind: 'state'; selection: LabSelection; live: LabLive }
  | { kind: 'ask' }
  | { kind: 'drafts' }
  | { kind: 'intent'; intent: LabIntent }
  | { kind: 'closed' };

function openChannel(): BroadcastChannel | null {
  try {
    return typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(LAB_CHANNEL);
  } catch (error) {
    console.warn('[widget lab] no broadcast channel', error);
    return null;
  }
}

function readStored(): { selection?: unknown; folds?: unknown } {
  try {
    const raw = globalThis.localStorage?.getItem(SELECTION_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return typeof parsed === 'object' && parsed !== null ? parsed : {};
  } catch (error) {
    console.warn('[widget lab] stored selection unreadable', error);
    return {};
  }
}

export class LabLink {
  selection = $state<LabSelection>(defaultSelection([], 'carnivore'));
  folds = $state<LabFolds>({ ...DEFAULT_FOLDS });
  live = $state<LabLive>({ ...EMPTY_LIVE });
  draftsSeq = $state(0);

  readonly #role: LabRole;
  readonly #widgets: readonly LabWidget[];
  readonly #channel: BroadcastChannel | null;
  readonly #onintent: ((intent: LabIntent) => void) | undefined;

  constructor(role: LabRole, widgets: readonly LabWidget[], theme: string, onintent?: (intent: LabIntent) => void) {
    this.#role = role;
    this.#widgets = widgets;
    this.#onintent = onintent;
    const stored = readStored();
    this.selection = normalizeSelection(stored.selection, widgets, theme);
    this.folds = normalizeFolds(stored.folds);
    this.#channel = openChannel();
    if (this.#channel) this.#channel.onmessage = (event: MessageEvent<Frame>) => this.#heard(event.data);
    if (role === 'viewer') this.#post({ kind: 'ask' });
    else {
      this.live = { ...this.live, menuOpen: true };
      this.publish();
    }
  }

  #persist(): void {
    try {
      globalThis.localStorage?.setItem(SELECTION_KEY, JSON.stringify({ selection: this.selection, folds: this.folds }));
    } catch (error) {
      console.warn('[widget lab] selection not stored', error);
    }
  }

  #post(frame: Frame): void {
    try {
      this.#channel?.postMessage(frame);
    } catch (error) {
      console.warn('[widget lab] channel post failed', error);
    }
  }

  #heard(frame: Frame | undefined): void {
    if (!frame) return;
    if (this.#role === 'viewer') {
      if (frame.kind === 'state') {
        this.selection = normalizeSelection(frame.selection, this.#widgets, frame.selection.theme);
        this.live = frame.live;
      } else if (frame.kind === 'closed') this.live = { ...this.live, menuOpen: false };
      else if (frame.kind === 'drafts') this.draftsSeq += 1;
      return;
    }
    const visible = typeof document === 'undefined' || document.visibilityState !== 'hidden';
    if (frame.kind === 'ask' && visible) this.publish();
    else if (frame.kind === 'intent') this.receive(frame.intent);
  }

  publish(): void {
    if (this.#role !== 'menu') return;
    this.#post({ kind: 'state', selection: $state.snapshot(this.selection), live: $state.snapshot(this.live) });
  }

  announceDrafts(): void {
    if (this.#role === 'menu') this.#post({ kind: 'drafts' });
  }

  set(patch: Partial<LabSelection>): void {
    this.selection = { ...this.selection, ...patch };
    this.#persist();
    this.publish();
  }

  replace(next: LabSelection): void {
    this.selection = next;
    this.#persist();
    this.publish();
  }

  setLive(patch: Partial<LabLive>): void {
    this.live = { ...this.live, ...patch };
    this.publish();
  }

  setFold(name: keyof LabFolds, open: boolean): void {
    this.folds = { ...this.folds, [name]: open };
    this.#persist();
  }

  send(intent: LabIntent): void {
    this.selection = applyIntent(this.selection, intent, this.#widgets);
    this.#persist();
    this.#post({ kind: 'intent', intent });
  }

  receive(intent: LabIntent): void {
    this.selection = applyIntent(this.selection, intent, this.#widgets);
    this.#persist();
    this.#onintent?.(intent);
    this.publish();
  }

  destroy(): void {
    if (this.#role === 'menu') this.#post({ kind: 'closed' });
    this.#channel?.close();
  }
}
