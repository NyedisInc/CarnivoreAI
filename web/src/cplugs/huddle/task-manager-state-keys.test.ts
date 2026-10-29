import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { STORED_STATES, stateKey } from './huddle-model';
import { STATUS_COLOR, statusKey, type TaskManagerStatus } from './huddle-status';
import { SECTION_ORDER, sectionKey } from './task-manager-status-sections';

const catalog = readFileSync(new URL('../../../../client/js/i18n/catalog.en.js', import.meta.url), 'utf8');
const keys = new Set([...catalog.matchAll(/^\s*'([a-z0-9_.]+)':/gm)].map((m) => m[1]));

test('every stored state, status and section has its catalog key', () => {
  for (const state of STORED_STATES) expect(keys.has(stateKey(state)), stateKey(state)).toBe(true);
  for (const status of Object.keys(STATUS_COLOR) as TaskManagerStatus[]) expect(keys.has(statusKey(status)), statusKey(status)).toBe(true);
  for (const section of SECTION_ORDER) expect(keys.has(sectionKey(section)), sectionKey(section)).toBe(true);
});

test('the check can fail: a state with no key is reported', () => {
  expect(keys.has(stateKey('no_such_state' as never))).toBe(false);
});
