import type { PlacementOptionValue } from '../../opscenter/widgets/placement-options';

export interface PlacementSource {
  setOption(key: string, option: string, value: PlacementOptionValue | null): unknown;
  setView(key: string, view: string): unknown;
  resetOptions(key: string): unknown;
  remove(key: string): boolean;
}
