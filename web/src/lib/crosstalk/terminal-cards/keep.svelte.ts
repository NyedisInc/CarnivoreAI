import { onEventFrame } from '../../../cplugs/sdk/terminal';
import { cardOf, sideEnabled, withCard, MAX_KEPT_CARDS, type Card, type CardFrame, type CardSide } from './model';
import { cardSettings } from './prefs.svelte';

const kept = $state<Record<string, Card[]>>({});

let stopFollowing: (() => void) | null = null;

function keysOf(id: string | null, uuid: string | null): string[] {
  return [id, uuid].filter((key): key is string => !!key);
}

export function keptFor(sessionId: string | null): Card[] {
  return (sessionId && kept[sessionId]) || [];
}

export function keepFrame(frame: CardFrame): void {
  if (!cardSettings.enabled || !cardSettings.keepCards) return;
  const ends: Array<[CardSide, string[]]> = [
    ['received', keysOf(frame.receiver_id, frame.receiver_uuid)],
    ['sent', keysOf(frame.sender_id, frame.sender_uuid)],
  ];
  for (const [side, keys] of ends) {
    if (!sideEnabled(cardSettings, side)) continue;
    const card = cardOf(frame, side);
    for (const key of keys) kept[key] = withCard(kept[key] ?? [], card, MAX_KEPT_CARDS);
  }
}

export function dismissKept(id: string, side: CardSide): void {
  for (const [key, cards] of Object.entries(kept)) {
    if (cards.some((card) => card.id === id && card.side === side)) {
      kept[key] = cards.filter((card) => !(card.id === id && card.side === side));
    }
  }
}

export function clearKept(): void {
  for (const key of Object.keys(kept)) delete kept[key];
}

export function followKept(): () => void {
  if (stopFollowing) return stopFollowing;
  const stop = onEventFrame<CardFrame>('crosstalk.card', keepFrame);
  stopFollowing = () => {
    stop();
    stopFollowing = null;
  };
  return stopFollowing;
}
