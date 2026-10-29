import { t } from '../sdk';
import { isDockPlacement, type Placement } from './lab-selection';

const LIST_MAX = 2;

export function placementLabel(one: Placement): string {
  return isDockPlacement(one) ? t(`cplug.devwidgetlab.dock.${one}`) : t(`cplug.devwidgetlab.host.${one}`);
}

export function placementSummary(placements: readonly Placement[]): string {
  return placements.length > LIST_MAX ? t('cplug.devwidgetlab.host.count', { count: placements.length }) : placements.map(placementLabel).join(', ');
}
