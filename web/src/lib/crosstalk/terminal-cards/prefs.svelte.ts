import { whenLegacyBootComplete } from '../../legacy-boot';
import { clearKept } from './keep.svelte';
import type { CardSettings } from './model';

export const CARD_FIELDS = {
  enabled: 'crosstalk_cards',
  senderCards: 'crosstalk_card_sender',
  receiverCards: 'crosstalk_card_receiver',
  keepCards: 'crosstalk_card_keep',
} as const;

export type CardSwitch = keyof typeof CARD_FIELDS;

export const CARD_DEFAULTS: Record<CardSwitch, boolean> = { enabled: false, senderCards: true, receiverCards: true, keepCards: false };

interface Bridge {
  read(field: string, localReader: () => unknown): unknown;
  write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
  follow?(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
  const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
  return found && typeof found.read === 'function' ? found : null;
}

export const cardSettings = $state<CardSettings & { enabled: boolean }>({ ...CARD_DEFAULTS });

function apply(name: CardSwitch, value: unknown): void {
  cardSettings[name] = typeof value === 'boolean' ? value : CARD_DEFAULTS[name];
  if (name === 'keepCards' && !cardSettings.keepCards) clearKept();
  if (name === 'enabled' && !cardSettings.enabled) clearKept();
}

export function readSettings(): void {
  const found = bridge();
  for (const name of Object.keys(CARD_FIELDS) as CardSwitch[]) apply(name, found?.read(CARD_FIELDS[name], () => null));
}

let following = false;

export function followSettings(target: Window | null = typeof window !== 'undefined' ? window : null): void {
  if (following) return;
  following = true;
  readSettings();
  const found = bridge();
  for (const name of Object.keys(CARD_FIELDS) as CardSwitch[]) found?.follow?.(CARD_FIELDS[name], (value) => apply(name, value));
  whenLegacyBootComplete(target, readSettings);
}

export async function setCardSwitch(name: CardSwitch, value: boolean): Promise<string | null> {
  const found = bridge();
  if (!found) return 'unavailable';
  const before = cardSettings[name];
  apply(name, value);
  const result = (await found.write(CARD_FIELDS[name], value, () => {})) as { status?: string; detail?: string } | null;
  const status = result && typeof result.status === 'string' ? result.status : '';
  if (status === 'committed' || status === 'unchanged') return null;
  apply(name, before);
  return (result && result.detail) || status || 'the server did not answer';
}
