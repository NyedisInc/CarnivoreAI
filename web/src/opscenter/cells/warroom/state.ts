import type { LocalStateField } from '../../widgets/shell/widget-state.svelte';
import { DEFAULT_TOGGLES } from '../../../lib/warroom/warroom-model';
import { PEEK_WIDTH_DEFAULT, PEEK_WIDTH_MAX } from '../../../lib/warroom/wall-layout';

const isBool = (value: unknown): value is boolean => typeof value === 'boolean';

const isPeekWidth = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= PEEK_WIDTH_MAX;

function device(def: boolean): LocalStateField<boolean> {
  return { home: 'device', default: def, valid: isBool };
}

export const WARROOM_STATE = {
  shells: device(DEFAULT_TOGGLES.shells),
  browsers: device(DEFAULT_TOGGLES.browsers),
  asleep: device(DEFAULT_TOGGLES.asleep),
  computers: device(DEFAULT_TOGGLES.computers),
  peekwidth: { home: 'device', default: PEEK_WIDTH_DEFAULT, valid: isPeekWidth },
} as const;
