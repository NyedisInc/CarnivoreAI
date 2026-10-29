/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { flowTab } from './flow-tab';
import { popoutTab } from '../../lib/dynamic-tabs/popout-tabs';
import { adopt, flowPrefs } from './flow-prefs.svelte';

describe('flow tab gate', () => {
  test('hidden by default and when the setting is false or unset', () => {
    expect(flowTab.present?.()).toBe(false);
    adopt({ settings: { showTab: false } });
    expect(flowTab.present?.()).toBe(false);
    adopt({ settings: {} });
    expect(flowPrefs.showTab).toBe(false);
  });

  test('shown when the setting is true, hidden again when it is switched off', () => {
    adopt({ settings: { showTab: true } });
    expect(flowTab.present?.()).toBe(true);
    adopt({ settings: { showTab: false } });
    expect(flowTab.present?.()).toBe(false);
  });

  test('the pop-out lists the tab whatever showTab says', () => {
    adopt({ settings: { showTab: false } });
    expect(flowTab.popout).toBe(true);
    expect(popoutTab('flow')?.id).toBe('flow');
  });
});
