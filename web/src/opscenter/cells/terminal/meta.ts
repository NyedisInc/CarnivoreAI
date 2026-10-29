
import { instanceName, isInstanceId } from '../../engine/meta';
import type { SlotId } from '../../engine/types';

export function isPrimaryInstance(id: SlotId | string): boolean {
  return isInstanceId(id as SlotId) && instanceName(id as SlotId) === '';
}
