
const STORE_PREFIX = 'carnivore.publicboard.visitor.';
const KEY_SHAPE = /^[A-Za-z0-9_-]{22}$/;
const LINK_ID = /^pbl_([A-Za-z0-9_-]{22})\./;

export type VisitorWindow = { localStorage: Pick<Storage, 'getItem' | 'setItem'>; crypto: Pick<Crypto, 'getRandomValues'> };

const fallback = new Map<string, string>();

export function newVisitorKey(source: Pick<Crypto, 'getRandomValues'>): string {
  const bytes = source.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function visitorKey(win: VisitorWindow, secret: string | null): string | null {
  const linkId = secret ? LINK_ID.exec(secret)?.[1] : undefined;
  if (!linkId) return null;
  const slot = STORE_PREFIX + linkId;
  try {
    const kept = win.localStorage.getItem(slot);
    if (kept && KEY_SHAPE.test(kept)) return kept;
    const made = newVisitorKey(win.crypto);
    win.localStorage.setItem(slot, made);
    return made;
  } catch (error) {
    if (!(error instanceof Error)) throw error;
    const made = fallback.get(slot) ?? newVisitorKey(win.crypto);
    fallback.set(slot, made);
    return made;
  }
}
