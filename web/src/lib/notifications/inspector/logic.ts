import { KINDS, TYPE_KIND, type NotifyKind } from '../../notify-card/contract.gen';
import { KIND_LIGHT, type NotifyActs, type NotifyCardData } from '../../notify-card/types';
import { DESKTOP, SCREEN, type RoutingSettings } from '../matrix/api';

export const SHAPES: Readonly<Record<string, readonly NotifyKind[]>> = {
    'session.question': ['yesno', 'choice'],
    'agent.message': ['crosstalk', 'file', 'link', 'image', 'video'],
};

export const defaultKind = (typeId: string): NotifyKind => TYPE_KIND[typeId] ?? 'notice';

export function kindFor(typeId: string, picked: string | undefined): NotifyKind {
    const shapes = SHAPES[typeId];
    return shapes && picked && (shapes as readonly string[]).includes(picked) ? (picked as NotifyKind) : defaultKind(typeId);
}

export interface Sample { readonly kind: NotifyKind; readonly card: NotifyCardData; readonly acts: NotifyActs; readonly body: string; readonly title: string; readonly sub: string; readonly lv: string }

export function sampleFor(fixtures: Readonly<Record<string, Sample>>, kind: NotifyKind, label: string): Sample | null {
    const base = fixtures[kind];
    if (!base) return null;
    return kind === 'notice' ? { ...base, title: label, card: { ...base.card, title: label } } : base;
}

export const deviceColumns = (iphones: readonly string[]): string[] => [SCREEN, DESKTOP, ...iphones];

export function isOn(settings: RoutingSettings, typeId: string, iphones: readonly string[]): boolean {
    return deviceColumns(iphones).some((column) => cellValue(settings, column, typeId));
}

export function cellValue(settings: RoutingSettings, column: string, typeId: string): boolean {
    const cell = column === SCREEN ? settings.screen[typeId] : column === DESKTOP ? settings.desktop[typeId] : settings.ticks[column]?.[typeId];
    return cell?.value === true;
}

export function writable(settings: RoutingSettings, column: string, typeId: string): boolean {
    const cell = column === SCREEN ? settings.screen[typeId] : column === DESKTOP ? settings.desktop[typeId] : settings.ticks[column]?.[typeId];
    return cell !== undefined && cell.locked !== true;
}

export const lightOf = (typeId: string): string => KIND_LIGHT[defaultKind(typeId)];

export const playable = (sound: string): boolean => ['ask', 'done', 'alarm', 'soft'].includes(sound);

export { KINDS };
