/* is gone with */
import { nextKey } from '../zone-shell/key-nav';

export function railKeyTarget(key: string, ids: readonly string[], current: string | null): string | null {
  return nextKey(key, ids, current, 'both', true);
}
