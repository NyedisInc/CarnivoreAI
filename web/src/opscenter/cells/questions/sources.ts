/* and the three */
import { builtInKinds, type AttentionKind } from '../../../lib/attention-kinds/kinds';
import type { PlacementOptions } from '../../widgets/placement-options';

export const COMBINED_ICON = 'bell';

export const ALL_OPTION = 'kind_all';

export function kindOptionKey(id: string): string {
  return `kind_${id}`;
}

export function isLiveOption(key: string): boolean {
  return key === ALL_OPTION || builtInKinds().some((kind) => kindOptionKey(kind.id) === key);
}

export function isRetiredOption(key: string): boolean {
  return key === 'counts' || key.startsWith('s_');
}

export function allOn(options: PlacementOptions | undefined): boolean {
  return options?.[ALL_OPTION] !== false;
}

export function kindOn(options: PlacementOptions | undefined, id: string): boolean {
  return options?.[kindOptionKey(id)] !== false;
}

export function copyListsKind(options: PlacementOptions | undefined, kindId: string): boolean {
  if (allOn(options)) return true;
  return builtInKinds().some((kind) => kind.id === kindId) && kindOn(options, kindId);
}

export function checkedKinds(options: PlacementOptions | undefined): AttentionKind[] {
  return allOn(options) ? [] : builtInKinds().filter((kind) => kindOn(options, kind.id));
}
