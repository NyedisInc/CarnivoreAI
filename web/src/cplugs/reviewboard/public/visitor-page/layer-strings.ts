import { t } from './strings';

export const LAYER_STRING_PREFIX = 'cplug.reviewboard.layer.';
const OWN_PREFIX = 'cplug.reviewboard.public.layer.';
export const LAYER_STRING_NAMES = ['yes', 'no', 'on', 'off', 'note', 'note_placeholder', 'show', 'unanswered', 'rank_up', 'rank_down', 'suggested', 'unsupported'] as const;

export function layerStrings(): Record<string, string> {
  return Object.fromEntries(LAYER_STRING_NAMES.map((name) => [`${LAYER_STRING_PREFIX}${name}`, t(`${OWN_PREFIX}${name}`)]));
}
