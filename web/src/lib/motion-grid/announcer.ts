import { createI18n } from '../../../../client/js/i18n/runtime.js';

export type AnnounceKey = 'motion.picked' | 'motion.moved' | 'motion.resized' | 'motion.cancelled' | 'motion.placed';

export interface Announcer {
  say(key: AnnounceKey, name: string): void;
  dispose(): void;
}

type Translate = (key: string, params?: Record<string, unknown>) => string;

let fallback: { t: Translate } | null = null;

function defaultTranslate(key: string, params?: Record<string, unknown>): string {
  const page = (globalThis as { CloudeI18n?: { t: Translate } }).CloudeI18n;
  fallback ??= page ?? (createI18n() as { t: Translate });
  return (page ?? fallback).t(key, params);
}

export function createAnnouncer(container: HTMLElement, translate: Translate = defaultTranslate): Announcer {
  const region = container.ownerDocument.createElement('div');
  region.className = 'motion-live';
  region.setAttribute('aria-live', 'polite');
  region.setAttribute('role', 'status');
  container.appendChild(region);
  return {
    say(key, name) {
      region.textContent = '';
      region.textContent = translate(key, { name });
    },
    dispose() {
      region.remove();
    },
  };
}
