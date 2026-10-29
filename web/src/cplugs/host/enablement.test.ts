import { afterEach, expect, test } from 'vitest';
import taskManagerManifest from '../../../../src/cplugs/huddle/cplug.json';
import { cplugEnabled, cplugEnablement, defaultEnabled } from './enablement.svelte';
import type { CplugManifest } from '../sdk';

const taskManager = taskManagerManifest as CplugManifest;

afterEach(() => {
  cplugEnablement.enabled = {};
  cplugEnablement.read = false;
});

test('huddle ships on for a clean install: its default is on and a stored off from the server wins', () => {
  expect(taskManager.default_enabled).toBe(true);
  expect(defaultEnabled(taskManager)).toBe(true);
  expect(cplugEnabled(taskManager)).toBe(true);
  cplugEnablement.enabled = { huddle: false };
  expect(cplugEnabled(taskManager)).toBe(false);
  cplugEnablement.enabled = { huddle: true };
  expect(cplugEnabled(taskManager)).toBe(true);
});

test('the rule can say on: core, default_enabled, or only free local permissions', () => {
  expect(defaultEnabled({ ...taskManager, tier: 'core' })).toBe(true);
  expect(defaultEnabled({ ...taskManager, default_enabled: true })).toBe(true);
  expect(defaultEnabled({ ...taskManager, default_enabled: undefined, permissions: { app: ['sessions.read', 'notify'] } })).toBe(true);
});

test('a declared default_enabled false is off even when the plugin asks for nothing', () => {
  expect(defaultEnabled({ ...taskManager, default_enabled: false, permissions: { app: [] } })).toBe(false);
  expect(defaultEnabled({ ...taskManager, default_enabled: undefined, permissions: { app: [] } })).toBe(true);
});
