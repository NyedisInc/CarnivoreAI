import { visibleItems } from '../manager-frame/manager-model';
import { WIDGET_CATEGORIES } from '../../opscenter/widgets/types';
import type { Translate } from '../sessions/types';
import { factKey, type WidgetItem } from './widgets-adapter';
import type { RailRow } from './PlacesRail.svelte';
import { PLACES, boardCell, fits, placeName, type PlaceId } from './places';
import { placedAnywhere } from './places-state.svelte';
import { setPlace, view, type PlacesView } from './places-view.svelte';

export type LensGroup = 'group' | 'place' | 'st';

const LABEL_JOIN = ' / ';

export interface Lens {
    groups: RailRow[];
    fits: RailRow[];
    states: RailRow[];
}

export const isOn = (item: WidgetItem): boolean => item.enabled !== false;

export const fitsIn = (item: WidgetItem, place: PlaceId): boolean => fits(item.manifest, isOn(item), place);

export const inAny = (item: WidgetItem): boolean => placedAnywhere(item.id, boardCell(item.manifest));

export const groupName = (group: string, t: Translate): string => t(factKey('category', group));

export function stTest(item: WidgetItem, st: string): boolean {
    return st === 'placed' ? inAny(item) : st === 'off' ? !isOn(item) : st === 'options' ? item.manifest.settings !== undefined : true;
}

export function passes(item: WidgetItem, skip?: LensGroup): boolean {
    if (skip !== 'group' && view.group !== 'all' && item.manifest.category !== view.group) return false;
    if (skip !== 'st' && view.st !== 'all' && !stTest(item, view.st)) return false;
    if (skip !== 'place' && view.show === 'fits' && view.place !== 'any' && !fitsIn(item, view.place)) return false;
    return true;
}

export function matchedItems(items: readonly WidgetItem[], query: string): readonly WidgetItem[] {
    const kept = new Set(visibleItems(items, query, []));
    return items.filter((item) => kept.has(item));
}

export function lensRows(items: readonly WidgetItem[], query: string, t: Translate): Lens {
    const matched = matchedItems(items, query);
    const count = (test: (item: WidgetItem) => boolean, skip: LensGroup): number => matched.filter((item) => passes(item, skip) && test(item)).length;
    return {
        groups: [
            { id: 'all', label: t('widgets.places.rail.everything'), count: count(() => true, 'group'), on: view.group === 'all' },
            ...WIDGET_CATEGORIES.map((group) => ({ id: group, glyph: group, label: groupName(group, t), count: count((item) => item.manifest.category === group, 'group'), on: view.group === group })),
        ],
        fits: PLACES.map((def) => ({ id: def.id, label: placeName(def.id, t), count: count((item) => fitsIn(item, def.id), 'place'), on: view.place === def.id, mark: { letter: def.mark, place: def.id } })),
        states: [
            { id: 'placed', label: t('widgets.places.rail.in_place'), count: count((item) => stTest(item, 'placed'), 'st'), on: view.st === 'placed' },
            { id: 'off', label: t('widgets.places.rail.off'), count: count((item) => stTest(item, 'off'), 'st'), on: view.st === 'off' },
            { id: 'options', label: t('widgets.places.rail.options'), count: count((item) => stTest(item, 'options'), 'st'), on: view.st === 'options' },
        ],
    };
}

export function lensLabel(lens: Lens): string {
    const picked = [...lens.groups.filter((row) => row.on && row.id !== 'all'), ...lens.fits.filter((row) => row.on), ...lens.states.filter((row) => row.on)];
    return (picked.length ? picked : lens.groups.filter((row) => row.on)).map((row) => row.label).join(LABEL_JOIN);
}

export function pickLens(group: LensGroup, id: string): void {
    if (group === 'place') setPlace(view.place === id ? 'any' : (id as PlaceId));
    else if (group === 'group') view.group = view.group === id && id !== 'all' ? 'all' : id;
    else view.st = view.st === id ? 'all' : (id as PlacesView['st']);
}
