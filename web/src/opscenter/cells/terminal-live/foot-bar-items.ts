import { preferenceField } from '../../../lib/preferences/field';
import { asFootBarItems, DEFAULT_FOOT_BAR_ITEMS, FOOT_BAR_ITEMS_FIELD, type FootBarItems } from './foot-plan';

const field = preferenceField<FootBarItems>(FOOT_BAR_ITEMS_FIELD, asFootBarItems, DEFAULT_FOOT_BAR_ITEMS);

export function readFootBarItems(): FootBarItems {
  return field.read();
}

export function saveFootBarItems(items: FootBarItems): Promise<string | null> {
  return field.save(items);
}

/* there is nothing */
export function followFootBarItems(apply: (items: FootBarItems) => void): () => void {
  return field.follow(apply);
}
