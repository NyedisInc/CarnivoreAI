import { expect, test } from 'vitest';

import taskManager from '../../../../src/plugins/taskmanager/carnivore.toml';
import { canonicalPluginId } from '../../plugins/host/renamed-ids';
import { settingsFeatureOf, settingsPluginOf } from '../settings-page/settings-hash';
import { pluginLinkOf } from './plugin-settings-link';

const OLD = taskManager.renamed_from;
const NEW = taskManager.id;

test('the shipped Task Manager manifest names an old id, so the cases below are not vacuous', () => {
  expect(OLD).toBeTruthy();
  expect(OLD).not.toBe(NEW);
});

test('an old id resolves to the new one and any other id to itself', () => {
  expect(canonicalPluginId(OLD)).toBe(NEW);
  expect(canonicalPluginId(NEW)).toBe(NEW);
  expect(canonicalPluginId('flow')).toBe('flow');
});

test('#plugins/<old>/settings opens the renamed plugin', () => {
  expect(pluginLinkOf(`#plugins/${OLD}/settings`)).toEqual({ cplugId: NEW, settings: true });
  expect(pluginLinkOf(`#plugins/${OLD}`)).toEqual({ cplugId: NEW, settings: false });
  expect(pluginLinkOf('#plugins/flow/settings')).toEqual({ cplugId: 'flow', settings: true });
});

test('#settings/plugin/<old> and #settings/features/<old> name the renamed plugin', () => {
  expect(settingsPluginOf(`#settings/plugin/${OLD}`)).toBe(NEW);
  expect(settingsFeatureOf(`#settings/features/${OLD}/settings`)).toEqual({ id: NEW, settings: true });
  expect(settingsPluginOf('#settings/plugin/flow')).toBe('flow');
});
