import { manifestById } from '../../../opscenter/widgets/core-manifests';
import { zoneItemKey, type ZoneItem } from '../../drawer-zone/zone-model';
import type { RailEdge } from '../../session-rail/rail-model';
import type { Translate } from '../../sessions/types';
import type { WidgetBarsView } from '../../widget-bars/bar-settings.svelte';
import { barThickness } from '../../widget-bars/bar-size';

export const STAGE_W = 1280;
export const STAGE_H = 640;

export const MIN_SCALE = 0.2;

export interface MockKey {
    key: string;
    title: string;
    icon: string;
    tone: string;
    item: ZoneItem;
}

export function mockScale(width: number): number {
    if (!(width > 0)) return 1;
    return Math.min(1, Math.max(MIN_SCALE, width / STAGE_W));
}

export function counterScale(k: number): number {
    return 1 / k;
}

export function mockKeys(items: readonly ZoneItem[], t: Translate): MockKey[] {
    const keys: MockKey[] = [];
    for (const item of items) {
        const manifest = manifestById(item.widget);
        if (manifest) keys.push({ key: zoneItemKey(item), title: t(manifest.titleKey), icon: manifest.icon, tone: manifest.iconTone, item });
    }
    return keys;
}

export function dockedPx(edge: RailEdge, view: WidgetBarsView): number {
    return view[edge].show ? barThickness(edge, view[edge].size) : 0;
}

export type EditCaption = { kind: 'items'; names: string } | { kind: 'hidden' } | { kind: 'empty' };

export function editCaption(shown: boolean, keys: readonly MockKey[]): EditCaption {
    if (!shown) return { kind: 'hidden' };
    return keys.length === 0 ? { kind: 'empty' } : { kind: 'items', names: keys.map((one) => one.title).join(', ') };
}
