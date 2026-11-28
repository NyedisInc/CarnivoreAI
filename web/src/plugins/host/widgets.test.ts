/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { entryFor, registeredInstanceKinds } from '../../opscenter/cells/registry';
import { metaFor } from '../../opscenter/engine/meta';
import { pluginKindMeta, pluginKinds } from '../../opscenter/engine/plugin-kinds';
import type { SlotId } from '../../opscenter/engine/types';
import { allPluginManifests, manifestById } from '../../opscenter/widgets/core-manifests';
import { pluginDeclarationFor } from '../../opscenter/widgets/fit-declarations';
import { taskmanagerCplug } from '../taskmanager';
import { cplugEnablement } from './enablement.svelte';
import { registerCplugWidgets, registerEnabledWidgets, unregisterCplugWidgets } from './widgets';

afterEach(() => {
  cplugEnablement.enabled = {};
  unregisterCplugWidgets(taskmanagerCplug);
});

describe('live widget registration & unregistration', () => {
  test('registerCplugWidgets registers all 4 tables and unregisterCplugWidgets removes them cleanly', () => {
    expect(registerCplugWidgets(taskmanagerCplug)).toEqual(['huddle.chat']);
    expect(pluginKinds()).toContain('huddle.chat');
    expect(pluginKindMeta('huddle.chat')).toBeDefined();
    expect(pluginDeclarationFor('huddle.chat')).toBeDefined();
    expect(manifestById('huddle.chat')).toBeDefined();
    expect(allPluginManifests()['huddle.chat']).toBeDefined();
    expect(entryFor('huddle.chat:agent:7' as SlotId)).toBeDefined();
    expect(registeredInstanceKinds()).toContain('huddle.chat');

    expect(unregisterCplugWidgets(taskmanagerCplug)).toEqual(['huddle.chat']);
    expect(unregisterCplugWidgets(taskmanagerCplug)).toEqual([]); // idempotent
    expect(pluginKinds()).not.toContain('huddle.chat');
    expect(pluginKindMeta('huddle.chat')).toBeUndefined();
    expect(pluginDeclarationFor('huddle.chat')).toBeUndefined();
    expect(manifestById('huddle.chat')).toBeUndefined();
    expect(allPluginManifests()['huddle.chat']).toBeUndefined();
    expect(entryFor('huddle.chat:agent:7' as SlotId)).toBeUndefined();
    expect(registeredInstanceKinds()).not.toContain('huddle.chat');

    expect(metaFor('huddle.chat:agent:7' as SlotId).titleKey).toBe('opscenter.cell.plugin_pending.title');
  });

  test('registerEnabledWidgets unregisters widgets when a plugin is disabled and re-registers when re-enabled', () => {
    cplugEnablement.enabled = { taskmanager: true };
    registerEnabledWidgets([taskmanagerCplug]);
    expect(allPluginManifests()['huddle.chat']).toBeDefined();
    expect(entryFor('huddle.chat:agent:1' as SlotId)).toBeDefined();

    cplugEnablement.enabled = { taskmanager: false };
    registerEnabledWidgets([taskmanagerCplug]);
    expect(allPluginManifests()['huddle.chat']).toBeUndefined();
    expect(pluginKindMeta('huddle.chat')).toBeUndefined();
    expect(pluginDeclarationFor('huddle.chat')).toBeUndefined();
    expect(entryFor('huddle.chat:agent:1' as SlotId)).toBeUndefined();

    cplugEnablement.enabled = { taskmanager: true };
    registerEnabledWidgets([taskmanagerCplug]);
    expect(allPluginManifests()['huddle.chat']).toBeDefined();
    expect(entryFor('huddle.chat:agent:1' as SlotId)).toBeDefined();
  });

  test('turning the renamed plugin off unregisters its kept old-id huddle.chat widget (#3260)', () => {
    cplugEnablement.enabled = { taskmanager: true };
    registerEnabledWidgets([taskmanagerCplug]);
    expect(pluginKinds()).toContain('huddle.chat');

    cplugEnablement.enabled = { taskmanager: false };
    registerEnabledWidgets([taskmanagerCplug]);
    expect(pluginKinds()).not.toContain('huddle.chat');
    expect(pluginKindMeta('huddle.chat')).toBeUndefined();
    expect(pluginDeclarationFor('huddle.chat')).toBeUndefined();
    expect(manifestById('huddle.chat')).toBeUndefined();
  });
});
