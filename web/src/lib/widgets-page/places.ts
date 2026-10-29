import type { Translate } from '../sessions/types';
import { sizeNameKey, type WidgetSizeName } from '../../opscenter/widgets/named-sizes';
import { widgetSizeNames } from '../../opscenter/widgets/info/widget-info';
import type { WidgetManifest } from '../../opscenter/widgets/types';

export type PlaceId = 'right' | 'bottom' | 'drawer' | 'glance' | 'board';

export interface PlaceDef {
    readonly id: PlaceId;
    readonly mark: string;
    readonly sizes: readonly WidgetSizeName[] | null;
}

export const PLACES: readonly PlaceDef[] = [
    { id: 'right', mark: 'R', sizes: ['tall', 'medium'] },
    { id: 'bottom', mark: 'B', sizes: ['medium', 'large', 'full'] },
    { id: 'drawer', mark: 'D', sizes: ['tall', 'wide'] },
    { id: 'glance', mark: 'G', sizes: ['small', 'wide', 'glance'] },
    { id: 'board', mark: 'H', sizes: null },
];

export const SIZE_ORDER: readonly WidgetSizeName[] = ['glance', 'small', 'wide', 'tall', 'medium', 'large', 'full'];

export function placeDef(id: PlaceId): PlaceDef {
    return PLACES.find((place) => place.id === id) ?? PLACES[0]!;
}

export function declaredSizes(manifest: WidgetManifest): WidgetSizeName[] {
    return widgetSizeNames(manifest);
}

export function fits(manifest: WidgetManifest, enabled: boolean, place: PlaceId): boolean {
    if (!enabled) return false;
    const sizes = placeDef(place).sizes;
    return sizes === null || declaredSizes(manifest).some((size) => sizes.includes(size));
}

export function placedSize(manifest: WidgetManifest, place: PlaceId): WidgetSizeName | null {
    const sizes = placeDef(place).sizes;
    const own = declaredSizes(manifest);
    if (sizes === null) return own[0] ?? null;
    return sizes.find((size) => own.includes(size)) ?? null;
}

export function orJoin(names: readonly string[], or: string): string {
    return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} ${or} ${names[names.length - 1]}`;
}

export function placeName(place: PlaceId, t: Translate): string {
    return t(`widgets.places.${place}.label`);
}

export function missingReason(manifest: WidgetManifest, enabled: boolean, place: PlaceId, t: Translate): string {
    if (!enabled) return t('widgets.places.reason.off');
    const names = declaredSizes(manifest).map((size) => t(sizeNameKey(size)));
    return t('widgets.places.reason.size', { place: t(`widgets.places.${place}.short`), sizes: orJoin(names, t('widgets.places.or')) });
}

export function boardCell(manifest: WidgetManifest): string | null {
    return manifest.instancing === 'singleton' && manifest.id.startsWith('core.') ? manifest.id.slice('core.'.length) : null;
}
