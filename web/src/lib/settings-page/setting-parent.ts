import { autoSleep } from '../auto-sleep/auto-sleep-store.svelte';
import { cardSettings } from '../crosstalk/terminal-cards/prefs.svelte';
import type { SettingDef } from './settings-registry';

export function isParentOff(def: SettingDef): boolean {
    if (def.parent === 'crosstalk_cards') return !cardSettings.enabled;
    const data = autoSleep.data;
    if (!def.parent || !data) return false;
    if (def.parent === 'auto_sleep') return !data.enabled;
    if (def.parent === 'auto_sleep_unread_blocks') return !data.enabled || data.unread_blocks_sleep !== false;
    return false;
}
