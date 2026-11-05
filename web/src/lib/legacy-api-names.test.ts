/** @vitest-environment jsdom */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, test } from 'vitest';
import { LEGACY_API_METHODS } from './legacy-api-names';
import { LegacyGlobalMissing, legacyApi, legacyAuth, requireLegacyGlobal } from './legacy-globals';

const CLIENT_JS = join(__dirname, '..', '..', '..', 'client', 'js');

const API_JS = ['api.js', ...readdirSync(CLIENT_JS).filter((f) => /^api-.+\.js$/.test(f)).sort()]
  .map((f) => readFileSync(join(CLIENT_JS, f), 'utf8'))
  .join('\n');

const definesMethod = (name: string): boolean => new RegExp(`^    (?:async )?${name}\\(`, 'm').test(API_JS);

describe('LEGACY_API_METHODS', () => {
  test('every name is a method api.js defines, and none is listed twice', () => {
    const missing = LEGACY_API_METHODS.filter((name) => !definesMethod(name));
    expect(missing, 'a name here that api.js does not define').toEqual([]);
    expect(new Set(LEGACY_API_METHODS).size).toBe(LEGACY_API_METHODS.length);
  });

  test('negative control: the check can go red for a name api.js lacks', () => {
    expect(definesMethod('getCatalogItemz')).toBe(false);
    expect(definesMethod('getCatalogItems')).toBe(true);
  });
});

describe('the accessors', () => {
  test('an absent global is a LegacyGlobalMissing, never undefined', () => {
    expect(() => legacyApi<{ call(path: string): Promise<unknown> }>()).toThrow(LegacyGlobalMissing);
    expect(() => legacyAuth()).toThrow(LegacyGlobalMissing);
    expect(() => requireLegacyGlobal('Themes')).toThrow('legacy_global_missing:Themes');
  });

  test('a present global is handed back as is', () => {
    const api = { call: async () => 1 };
    (window as unknown as { API?: unknown }).API = api;
    try {
      expect(legacyApi<typeof api>()).toBe(api);
    } finally {
      delete (window as unknown as { API?: unknown }).API;
    }
  });
});

export function typoIsRefused(): void {
  // @ts-expect-error getCatalogItemz is not in LEGACY_API_METHODS
  legacyApi<{ getCatalogItemz(): void }>();
  legacyApi<{ getCatalogItems(): void }>();
}
