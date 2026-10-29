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
    bridge()?.follow(this.field, (value) => this.#apply(value));
    whenLegacyBootComplete(target, () => this.reload());
  }

  reload(): void {
    this.#apply(bridge()?.read(this.field, () => null));
  }

  async write(value: unknown): Promise<void> {
    const found = bridge();
    if (found) await found.write(this.field, value, () => {});
  }
}
