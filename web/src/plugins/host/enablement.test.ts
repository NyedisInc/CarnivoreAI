import { afterEach, expect, test } from 'vitest';
import taskManagerManifest from '../../../../src/plugins/taskmanager/carnivore.toml';
import shareManifest from '../../../../src/plugins/share/carnivore.toml';
import argentManifest from '../../../../src/plugins/argent/carnivore.toml';
import sessionchatManifest from '../../../../src/plugins/sessionchat/carnivore.toml';
import timemachineManifest from '../../../../src/plugins/timemachine/carnivore.toml';
import tmdevtoolsManifest from '../../../../src/plugins/tmdevtools/carnivore.toml';
import devwidgetlabManifest from '../../../../src/plugins/devwidgetlab/carnivore.toml';
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
  cplugEnablement.enabled = { taskmanager: false };
  expect(cplugEnabled(taskManager)).toBe(false);
  cplugEnablement.enabled = { taskmanager: true };
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

test('v2 carnivore.toml permission shape gates defaultEnabled accurately', () => {
  const baseV2: CplugManifest = {
    schema: 2,
    id: 'v2sample',
    name: 'V2 Sample',
    description: 'v2 shape',
    version: '1.0.0',
    tier: 'builtin',
  };
  expect(defaultEnabled({ ...baseV2, permissions: { read: ['sessions'], write: ['notify'] } })).toBe(true);
  expect(defaultEnabled({ ...baseV2, permissions: { read: ['sessions', 'ledger'] } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, permissions: { write: ['exports'] } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, permissions: { network: [{ host: 'api.example.com' }] } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, default_enabled: true, permissions: { read: ['ledger'] } })).toBe(true);
  expect(defaultEnabled({ ...baseV2, default_enabled: false, permissions: { read: ['sessions'] } })).toBe(false);
});

test('v2 carnivore.toml top-level services, events, webhooks, ui.contribute, and tiers match Python state.default_state()', () => {
  const baseV2: CplugManifest = {
    schema: 2,
    id: 'v2probe',
    name: 'V2 Probe',
    description: 'v2 parity',
    version: '1.0.0',
    tier: 'builtin',
  };

  expect(defaultEnabled(baseV2)).toBe(true);
  expect(defaultEnabled({ ...baseV2, services: { consumes: ['pulse.state'] } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, services: { provides: [{ name: 'v2probe.svc', methods: ['ping'] }] } })).toBe(true);

  expect(defaultEnabled({ ...baseV2, events: { emit: ['v2probe.done'] } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, events: { on: ['pulse.ready'] } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, events: { on: ['feed.custom'] } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, events: { on: ['feed.meta', 'feed.scrubbed', 'feed.raw', 'mcp.health'] } })).toBe(true);

  expect(defaultEnabled({ ...baseV2, webhooks: { hook1: { hmac_secret: 'HOOK_SECRET' } } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, ui: { contribute: { 'session.row_actions': [{ id: 'x', label: 'X' }] } } })).toBe(false);

  expect(defaultEnabled({ ...baseV2, permissions: { secrets: ['MY_KEY'] } })).toBe(true);
  expect(defaultEnabled({ ...baseV2, permissions: { secrets: [{ key: 'MY_KEY', label: 'My Key' }] } })).toBe(true);
  expect(defaultEnabled({ ...baseV2, permissions: { secrets: ['MY_KEY'], network: [{ host: 'api.example.com' }] } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, permissions: { secrets: ['MY_KEY'], lan: ['192.168.1.10'] } })).toBe(false);
  expect(defaultEnabled({ ...baseV2, permissions: { secrets: ['MY_KEY'] }, webhooks: { hook1: { hmac_secret: 'MY_KEY' } } })).toBe(false);

  expect(defaultEnabled({ ...baseV2, tier: 'catalog' })).toBe(false);
  expect(defaultEnabled({ ...baseV2, tier: 'catalog', default_enabled: true })).toBe(false);
  expect(defaultEnabled({ ...baseV2, tier: 'local' })).toBe(false);
  expect(defaultEnabled({ ...baseV2, tier: 'local', default_enabled: true })).toBe(false);
  expect(defaultEnabled({ ...baseV2, tier: 'dev', default_enabled: true })).toBe(false);
});

test('Batch 2 built-in carnivore.toml manifests preserve defaultEnabled() parity', () => {
  expect(defaultEnabled(shareManifest as CplugManifest)).toBe(true);
  expect(defaultEnabled(argentManifest as CplugManifest)).toBe(false);
  expect(defaultEnabled(sessionchatManifest as CplugManifest)).toBe(false);
  expect(defaultEnabled(timemachineManifest as CplugManifest)).toBe(false);
  expect(defaultEnabled(tmdevtoolsManifest as CplugManifest)).toBe(false);
  expect(defaultEnabled(devwidgetlabManifest as CplugManifest)).toBe(false);
});
