import { t } from '../i18n/index.svelte';
import { whenLegacyBootComplete } from '../legacy-boot';

export interface Bridge {
  read(field: string, localReader: () => unknown): unknown;
  write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
  writeMany(entries: { field: string; value: unknown; localWriter: () => void }[]): Promise<unknown>;
  follow(field: string, apply: (value: unknown) => void): () => void;
}

export function bridge(): Bridge | null {
  const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
  return found && typeof found.read === 'function' ? found : null;
}

export const WRITE_REFUSED = new Set(['failed', 'refused', 'stale_revision']);

const SAVED = new Set(['committed', 'unchanged']);

export async function savePreference(field: string, value: unknown): Promise<string | null> {
  const found = bridge();
  if (!found) return 'unavailable';
  const result = (await found.write(field, value, () => {})) as { status?: string; detail?: string } | null;
  const status = result && typeof result.status === 'string' ? result.status : '';
  if (SAVED.has(status)) return null;
  return (result && result.detail) || status || t('prefs.save.no_answer');
}

/* there is nothing */
export function followPreference<T>(field: string, coerce: (value: unknown) => T, apply: (value: T) => void): () => void {
  const found = bridge();
  if (!found || typeof found.follow !== 'function') return () => {};
  return found.follow(field, (value) => apply(coerce(value)));
}

export class PreferenceField {
  readonly field: string;
  readonly #apply: (value: unknown) => void;
  #started = false;

  constructor(field: string, apply: (value: unknown) => void) {
    this.field = field;
    this.#apply = apply;
  }

  start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
    if (this.#started) return;
    this.#started = true;
    this.reload();
    bridge()?.follow?.(this.field, (value) => this.#apply(value));
    whenLegacyBootComplete(target, () => this.reload());
  }

  reload(): void {
    this.#apply(bridge()?.read(this.field, () => null));
  }

  async write(value: unknown): Promise<void> {
    const found = bridge();
    if (!found) return;
    const result = (await found.write(this.field, value, () => {})) as { status?: string } | null;
    if (result && typeof result.status === 'string' && WRITE_REFUSED.has(result.status)) {
      console.warn('PreferenceField: the server did not take the change, reloading', this.field, result.status);
      this.reload();
    }
  }
}
