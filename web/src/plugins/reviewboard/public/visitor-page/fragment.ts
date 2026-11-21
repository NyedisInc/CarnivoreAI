
export const LINK_HEADER = 'Carnivore-Board-Link';
const STORE_KEY = 'publicboard.link';

export type FragmentWindow = Pick<Window, 'location' | 'history' | 'sessionStorage'>;

export function takeLinkSecret(win: FragmentWindow): string | null {
  const raw = win.location.hash.slice(1);
  if (raw !== '') {
    win.history.replaceState(null, '', win.location.pathname + win.location.search);
    const secret = decode(raw);
    if (secret !== null) remember(win, secret);
    return secret;
  }
  return recall(win);
}

function decode(raw: string): string | null {
  try {
    const text = decodeURIComponent(raw);
    return text === '' ? null : text;
  } catch (error) {
    if (error instanceof URIError) return null;
    throw error;
  }
}

function remember(win: FragmentWindow, secret: string): void {
  try {
    win.sessionStorage.setItem(STORE_KEY, secret);
  } catch (error) {
    if (!(error instanceof Error)) throw error;
  }
}

function recall(win: FragmentWindow): string | null {
  try {
    return win.sessionStorage.getItem(STORE_KEY);
  } catch (error) {
    if (!(error instanceof Error)) throw error;
    return null;
  }
}

export function forgetLinkSecret(win: FragmentWindow): void {
  try {
    win.sessionStorage.removeItem(STORE_KEY);
  } catch (error) {
    if (!(error instanceof Error)) throw error;
  }
}
