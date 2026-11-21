import { t } from '../sdk';

export const LAYER_STRING_PREFIX = 'cplug.reviewboard.layer.';
export const LAYER_STRING_NAMES = ['yes', 'no', 'on', 'off', 'note', 'note_placeholder', 'show', 'unanswered', 'rank_up', 'rank_down', 'suggested', 'unsupported'] as const;

export function layerStrings(): Record<string, string> {
  return Object.fromEntries(LAYER_STRING_NAMES.map((name) => [`${LAYER_STRING_PREFIX}${name}`, t(`${LAYER_STRING_PREFIX}${name}`)]));
}
