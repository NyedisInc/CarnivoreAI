import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import type { Fetcher, ItemSettingsPayload, SettingValue } from './api';

type Node = { enabled: boolean | null; values: Record<string, SettingValue>; revision: number };

function payload(held: Map<string, Node>, id: string, schema: WidgetSettingsSchema | null): ItemSettingsPayload {
    const node = held.get(id) ?? { enabled: null, values: {}, revision: 0 };
    return { kind: 'widget', id, enabled: node.enabled, switchable: true, values: { ...node.values }, dropped: [], schema, revision: node.revision };
}

export function memoryFetcher(schemas: Readonly<Record<string, WidgetSettingsSchema | null>>): Fetcher {
    const held = new Map<string, Node>();
    let revision = 0;
    return (async (path: string, init: RequestInit = {}) => {
        if (path === '/widgets') {
            return { widgets: Object.values(CORE_MANIFESTS).map((m) => ({
                id: m.id, instancing: m.instancing,
                enabled: m.instancing === 'singleton' ? held.get(m.id)?.enabled !== false : null,
                has_settings: Boolean(m.settings),
            })) };
        }
        const id = decodeURIComponent(path.split('/').pop() ?? '');
        if (init.method === 'PATCH') {
            const patch = JSON.parse(String(init.body)) as { values?: Record<string, SettingValue | null>; enabled?: boolean };
            const node = held.get(id) ?? { enabled: null, values: {}, revision: 0 };
            for (const [key, value] of Object.entries(patch.values ?? {})) {
                if (value === null) delete node.values[key];
                else node.values[key] = value;
            }
            if (patch.enabled !== undefined) node.enabled = patch.enabled;
            revision += 1;
            node.revision = revision;
            held.set(id, node);
            return { status: 'committed', ...payload(held, id, schemas[id] ?? null) };
        }
        return payload(held, id, schemas[id] ?? null);
    }) as Fetcher;
}
