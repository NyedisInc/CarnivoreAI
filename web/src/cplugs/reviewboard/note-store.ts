
export const NOTE_KEY_PREFIX = 'carnivore.reviewboard.note:';
export const SIZE_KEY = 'carnivore.reviewboard.notes_size';
export const DEFAULT_SIZE: PanelSize = { width: 440, height: 380 };
export const MAX_NOTE = 8000;
export const COUNTER_FROM = 7000;

export interface PanelSize { width: number; height: number }

function guarded<T>(work: (store: Storage) => T): T | null {
  try {
    return typeof localStorage === 'undefined' ? null : work(localStorage);
  } catch (error) {
    if (error instanceof DOMException || error instanceof TypeError) return null;
    throw error;
  }
}

export function noteKey(slug: string, revision: string): string {
  return `${NOTE_KEY_PREFIX}${slug}|${revision}`;
}

export function readNote(key: string): string {
  return guarded((s) => s.getItem(key)) ?? '';
}

export function writeNote(key: string, text: string): void {
  guarded((s) => (text.trim() ? s.setItem(key, text) : s.removeItem(key)));
}

export class NoteKeeper {
  private key = '';

  follow(key: string, text: string): string | null {
    if (!key) return null;
    if (key !== this.key) {
      this.key = key;
      const kept = readNote(key);
      if (!text && kept) return kept.slice(0, MAX_NOTE);
    }
    writeNote(key, text);
    return null;
  }
}

export function readSize(): PanelSize {
  const raw = guarded((s) => s.getItem(SIZE_KEY));
  if (!raw) return DEFAULT_SIZE;
  try {
    const parsed = JSON.parse(raw) as Partial<PanelSize> | null;
    const width = Number(parsed?.width);
    const height = Number(parsed?.height);
    return width > 0 && height > 0 ? { width: Math.round(width), height: Math.round(height) } : DEFAULT_SIZE;
  } catch (error) {
    if (error instanceof SyntaxError) return DEFAULT_SIZE;
    throw error;
  }
}

export function writeSize(size: PanelSize): void {
  guarded((s) => s.setItem(SIZE_KEY, JSON.stringify({ width: Math.round(size.width), height: Math.round(size.height) })));
}
