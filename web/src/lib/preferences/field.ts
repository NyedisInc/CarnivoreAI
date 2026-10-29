import { bridge } from '../zone-shell/preference-field';

const SAVED = new Set(['committed', 'unchanged']);

export const SAVE_UNAVAILABLE = 'unavailable';

export const SAVE_NO_ANSWER = 'the server did not answer';

export interface TypedPreferenceField<T> {
  read(): T;
  save(value: T): Promise<string | null>;
  follow(apply: (value: T) => void): () => void;
}

export function preferenceField<T>(name: string, coerce: (value: unknown) => T, fallback: T): TypedPreferenceField<T> {
  return {
    read: () => coerce(bridge()?.read(name, () => fallback)),
    async save(value) {
      const found = bridge();
      if (!found) return SAVE_UNAVAILABLE;
      const result = (await found.write(name, value, () => {})) as { status?: string; detail?: string } | null;
      const status = result && typeof result.status === 'string' ? result.status : '';
      if (SAVED.has(status)) return null;
      return (result && result.detail) || status || SAVE_NO_ANSWER;
    },
    follow(apply) {
      const found = bridge();
      if (!found || typeof found.follow !== 'function') return () => {};
      return found.follow(name, (value) => apply(coerce(value)));
    },
  };
}
