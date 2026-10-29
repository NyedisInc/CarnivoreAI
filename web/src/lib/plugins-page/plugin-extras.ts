import type { Component } from 'svelte';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import { NO_CONTEXT, surfacesOf } from '../plugins/registry';
import HuddleSwarmSettings from './HuddleSwarmSettings.svelte';

const SAVE_OWN_FIELDS: readonly string[] = ['vaultLocation', 'vaultFolderOptOut'];

export const PLUGIN_SETTINGS_EXTRAS: Readonly<Record<string, Component<Record<string, never>>>> = {
    huddle: HuddleSwarmSettings as unknown as Component<Record<string, never>>,
};

export function settingsExtraOf(cplugId: string): Component<Record<string, never>> | undefined {
    return PLUGIN_SETTINGS_EXTRAS[cplugId] ?? surfacesOf('settings-panel').find((c) => c.id === cplugId && c.enabled(NO_CONTEXT))?.payload.Panel;
}

export function visibleSchema(cplugId: string, schema: WidgetSettingsSchema): WidgetSettingsSchema {
    if (cplugId === 'save' && SAVE_OWN_FIELDS.some((name) => schema.fields[name])) {
        return { ...schema, fields: Object.fromEntries(Object.entries(schema.fields).filter(([name]) => !SAVE_OWN_FIELDS.includes(name))) };
    }
    return schema;
}

export function formIsShown(shown: WidgetSettingsSchema | null, hasExtra: boolean): boolean {
    if (!shown) return false;
    return Object.keys(shown.fields).length > 0 || !hasExtra;
}
