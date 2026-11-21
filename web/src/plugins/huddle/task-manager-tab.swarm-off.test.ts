import { describe, expect, test } from 'vitest';
import { taskManagerTab } from './task-manager-tab';
import { taskManagerPrefs } from './task-manager-prefs.svelte';
import { swarmSwitch } from '../../lib/swarm-switch/control.svelte';
import { swarmFlyout } from './swarm-flyout';
import { sidebarTabs, tabRegistry } from '../sdk';

describe('the Swarm tab and its rail flyout follow the pushed swarm switch (#1983)', () => {
  test('hidden while off, back as soon as the pushed state says on', () => {
    taskManagerPrefs.showTab = true;
    if (!tabRegistry.get(taskManagerTab.id)) tabRegistry.register(taskManagerTab);
    swarmSwitch.data = null;
    expect(taskManagerTab.present?.()).toBe(true);
    swarmSwitch.data = { enabled: false };
    expect(taskManagerTab.present?.()).toBe(false);
    expect(taskManagerTab.open?.()).toBe(false);
    expect(swarmFlyout.present?.()).toBe(false);
    expect(sidebarTabs.isPresent(taskManagerTab)).toBe(false);
    swarmSwitch.data = { enabled: true };
    expect(taskManagerTab.present?.()).toBe(true);
    expect(swarmFlyout.present?.()).toBe(true);
  });
});
