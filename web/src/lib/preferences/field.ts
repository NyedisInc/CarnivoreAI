import { bridge, followPreference, savePreference } from '../zone-shell/preference-field';

export interface TypedPreferenceField<T> {
  read(): T;
  save(value: T): Promise<string | null>;
  follow(apply: (value: T) => void): () => void;
}

export function preferenceField<T>(name: string, coerce: (value: unknown) => T, fallback: T): TypedPreferenceField<T> {
  return {
    read: () => coerce(bridge()?.read(name, () => fallback)),
    save: (value) => savePreference(name, value),
    follow: (apply) => followPreference(name, coerce, apply),
  };
}
