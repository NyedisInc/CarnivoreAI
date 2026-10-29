import { PreferenceField } from '../zone-shell/preference-field';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';

export const PREFERENCE_FIELD = 'rail_hidden_icons';

const view = $state<{ ids: string[] }>({ ids: [] });

function clean(value: unknown): string[] {
  return Array.isArray(value) ? [...new Set(value.filter((v): v is string => typeof v === 'string' && v !== ''))] : [];
}

const field = new PreferenceField(PREFERENCE_FIELD, (value) => {
  view.ids = clean(value);
});

export function shownIcons<T extends { id: string }>(items: readonly T[], hidden: readonly string[], editing: boolean): T[] {
  return editing ? [...items] : items.filter((item) => !hidden.includes(item.id));
}

export function railIconsShown<T extends { id: string }>(items: readonly T[]): T[] {
  return shownIcons(items, view.ids, layoutEditor.active);
}

export function railIconHidden(id: string): boolean {
  return view.ids.includes(id);
}

export async function setRailIconHidden(id: string, hidden: boolean): Promise<void> {
  const next = hidden ? [...new Set([...view.ids, id])] : view.ids.filter((x) => x !== id);
  view.ids = next;
  await field.write(next.length > 0 ? next : null);
}

export function startRailIcons(): void {
  field.start();
}
