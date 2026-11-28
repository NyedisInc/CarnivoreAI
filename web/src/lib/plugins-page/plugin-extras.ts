import type { Component } from 'svelte';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import { NO_CONTEXT, surfacesOf } from '../plugins/registry';

export function settingsExtraOf(cplugId: string): Component<Record<string, never>> | undefined {
    return surfacesOf('settings-panel').find((c) => c.id === cplugId && c.enabled(NO_CONTEXT))?.payload.Panel;
}

export function visibleSchema(schema: WidgetSettingsSchema): WidgetSettingsSchema {
    const hasHidden = Object.values(schema.fields).some((field) => field.hidden === true);
    if (!hasHidden) return schema;
    return { ...schema, fields: Object.fromEntries(Object.entries(schema.fields).filter(([, field]) => field.hidden !== true)) };
}

export function formIsShown(shown: WidgetSettingsSchema | null, _hasExtra = false): boolean {
    return Boolean(shown && Object.keys(shown.fields).length > 0);
}
