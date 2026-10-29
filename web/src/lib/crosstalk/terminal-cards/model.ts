
export interface CardFrame {
  type?: string;
  id: string;
  thread: string | null;
  sender_id: string | null;
  sender_uuid: string | null;
  sender_name: string | null;
  sender_provider: string | null;
  sender_model: string | null;
  receiver_id: string | null;
  receiver_uuid: string | null;
  receiver_name: string | null;
  receiver_provider: string | null;
  receiver_model: string | null;
  preview: string;
  at: number;
}

export type CardSide = 'sent' | 'received';

export interface Card {
  id: string;
  side: CardSide;
  peer: string;
  provider: string;
  model: string;
  preview: string;
  at: number;
  thread: string | null;
}

export interface CardSettings {
  senderCards: boolean;
  receiverCards: boolean;
  keepCards: boolean;
}

export const CARD_TTL_MS = 20_000;
export const MAX_KEPT_CARDS = 20;
export const MAX_CARDS = 3;

export function sideOf(frame: CardFrame, sessionId: string | null | undefined): CardSide | null {
  if (!sessionId) return null;
  if (frame.receiver_id === sessionId || frame.receiver_uuid === sessionId) return 'received';
  if (frame.sender_id === sessionId || frame.sender_uuid === sessionId) return 'sent';
  return null;
}

export function sideEnabled(settings: CardSettings, side: CardSide): boolean {
  return side === 'sent' ? settings.senderCards !== false : settings.receiverCards !== false;
}

export function cardOf(frame: CardFrame, side: CardSide): Card {
  const sent = side === 'sent';
  return {
    id: frame.id,
    side,
    peer: (sent ? frame.receiver_name || frame.receiver_id : frame.sender_name) || '',
    provider: (sent ? frame.receiver_provider : frame.sender_provider) || '',
    model: (sent ? frame.receiver_model : frame.sender_model) || '',
    preview: frame.preview,
    at: frame.at,
    thread: frame.thread,
  };
}

export function withCard(cards: readonly Card[], card: Card, cap: number = MAX_CARDS): Card[] {
  if (cards.some((c) => c.id === card.id)) return [...cards];
  return [...cards, card].slice(-cap);
}
