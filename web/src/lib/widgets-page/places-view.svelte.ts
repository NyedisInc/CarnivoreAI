import type { PlaceId } from './places';

export interface PlacesView {
    place: 'any' | PlaceId;
    board: string;
    sort: 'group' | 'name';
    show: 'all' | 'fits';
    group: string;
    st: 'all' | 'placed' | 'off' | 'options';
}

export const view: PlacesView = $state({ place: 'any', board: '', sort: 'group', show: 'all', group: 'all', st: 'all' });

export function setPlace(place: 'any' | PlaceId): void {
    view.place = place;
    if (place === 'any') view.show = 'all';
}

export function resetView(): void {
    view.place = 'any';
    view.board = '';
    view.sort = 'group';
    view.show = 'all';
    view.group = 'all';
    view.st = 'all';
}
