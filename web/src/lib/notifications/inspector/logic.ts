import { TYPE_KIND, type NotifyKind } from '../../notify-card/contract.gen';
import { KIND_LIGHT, type NotifyActs, type NotifyCardData } from '../../notify-card/types';
import type { RouteCell, RoutesBody, Target } from './api';

export interface Sample { readonly kind: NotifyKind; readonly card: NotifyCardData; readonly acts: NotifyActs; readonly body: string; readonly title: string; readonly sub: string; readonly lv: string }

export type Tri = 'all' | 'some' | 'none';

export const defaultKind = (typeId: string): NotifyKind => TYPE_KIND[typeId] ?? 'notice';

export const GROUP_KIND: Readonly<Record<string, NotifyKind>> = {
    needs_you: 'permission', sessions: 'finished', messages: 'crosstalk', swarm: 'swarm', health: 'notice', security: 'notice', automations: 'notice', app: 'appupdate',
};

export const kindOf = (typeId: string | null, family: string): NotifyKind => (typeId ? defaultKind(typeId) : (GROUP_KIND[family] ?? 'notice'));

export function sampleFor(fixtures: Readonly<Record<string, Sample>>, kind: NotifyKind, label: string): Sample | null {
    const base = fixtures[kind];
    if (!base) return null;
    return kind === 'notice' ? { ...base, title: label, card: { ...base.card, title: label } } : base;
}

export const lightOf = (kind: NotifyKind): string => KIND_LIGHT[kind];

export function tri(values: readonly boolean[]): Tri {
    const on = values.filter(Boolean).length;
    return on === 0 ? 'none' : on === values.length ? 'all' : 'some';
}

export const known = (routes: RoutesBody | null, ids: readonly string[]): string[] => ids.filter((id) => routes?.types[id] !== undefined);

export const groupState = (routes: RoutesBody | null, ids: readonly string[]): Tri => tri(known(routes, ids).map((id) => routes?.types[id]?.on === true));

export const cellOf = (routes: RoutesBody | null, id: string, iid: string, target: Target): RouteCell | undefined => routes?.types[id]?.cells[iid]?.[target];

const writableCells = (routes: RoutesBody | null, ids: readonly string[], iid: string, target: Target): RouteCell[] =>
    known(routes, ids).flatMap((id) => { const c = cellOf(routes, id, iid, target); return c && !c.locked ? [c] : []; });

export function groupCol(routes: RoutesBody | null, ids: readonly string[], iid: string, target: Target): { state: Tri; writable: boolean; unset: boolean } {
    const cells = writableCells(routes, ids, iid, target);
    return { state: tri(cells.map((c) => c.value === true)), writable: cells.length > 0, unset: cells.length > 0 && cells.every((c) => c.source === 'unknown') };
}

export const hueClass = (hue: number): string => `ins-hue-${(((hue % 4) + 4) % 4) + 1}`;

export const cornerAllowed = (urgency: string): boolean => urgency !== 'passive';

export function targetsOn(routes: RoutesBody | null, ids: readonly string[], iid: string): Target[] {
    return (['app', 'desk', 'phone'] as const).filter((tg) => known(routes, ids).some((id) => cellOf(routes, id, iid, tg)?.value === true));
}

export const anyTarget = (routes: RoutesBody | null, ids: readonly string[], target: Target): boolean =>
    (routes?.computers ?? []).some((c) => known(routes, ids).some((id) => cellOf(routes, id, c.install_id, target)?.value === true));

export { playable } from '../sound-player';
