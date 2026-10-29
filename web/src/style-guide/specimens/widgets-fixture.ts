import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import { createWidgetsAdapter } from '../../lib/widgets-page/widgets-adapter';
import {
    createItemSettingsController,
    type ItemSettingsController,
} from '../../lib/item-settings/item-settings-controller.svelte';
import { memoryFetcher } from '../../lib/item-settings/memory-fetcher';
import type { ManagerAdapter } from '../../lib/manager-frame/types';
import { t } from '../../lib/i18n/index.svelte';

const CORE_SCHEMAS = Object.fromEntries(Object.values(CORE_MANIFESTS).map((m) => [m.id, m.settings ?? null]));

const CORE_FETCHER = memoryFetcher(CORE_SCHEMAS);

export const widgetsSpecimenAdapter: ManagerAdapter = createWidgetsAdapter(
    t, CORE_MANIFESTS, CORE_FETCHER, async () => {}, () => {},
);

export function specimenSettingsFor(id: string): ItemSettingsController {
    return createItemSettingsController('widget', id, t, CORE_FETCHER, async () => {});
}

export const EVERY_KIND_SCHEMA: WidgetSettingsSchema = {
    version: 1,
    fields: {
        showSystem: { kind: 'boolean', labelKey: 'widgets.setting.activity_log.show_system', default: true },
        rows: { kind: 'number', labelKey: 'item_settings.specimen.rows', default: 8, min: 1, max: 50 },
        order: { kind: 'enum', labelKey: 'item_settings.specimen.order', default: 'newest', options: ['newest', 'oldest'] },
        caption: { kind: 'string', labelKey: 'item_settings.specimen.caption', default: '', maxLength: 40 },
    },
};

export function everyKindController(): ItemSettingsController {
    return createItemSettingsController('widget', 'specimen.every-kind', t,
        memoryFetcher({ 'specimen.every-kind': EVERY_KIND_SCHEMA }), async () => {});
}
