import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { DeclaredAction } from '../../opscenter/widgets/menu/declared-actions.svelte';

function setOf(action: DeclaredAction): string | null {
  if (action.group !== undefined) return `group:${action.group}`;
  if (action.checked === undefined || action.toggle) return null;
  const colon = action.id.indexOf(':');
  return colon > 0 ? `set:${action.id.slice(0, colon)}` : 'set:';
}

function nodeOf(action: DeclaredAction): MenuNode {
  return {
    id: action.id,
    label: action.label,
    ...(action.checked === undefined ? {} : { checked: action.checked }),
    ...(action.toggle ? { toggle: true } : {}),
    ...(action.blocked ? { blocked: action.blocked } : {}),
    run: action.run,
  };
}

export function declaredGroups(actions: readonly DeclaredAction[]): MenuNode[][] {
  const groups: MenuNode[][] = [];
  let openSet: string | null | undefined;
  for (const action of actions) {
    const set = setOf(action);
    const last = groups[groups.length - 1];
    if (last && set === openSet) last.push(nodeOf(action));
    else groups.push([nodeOf(action)]);
    openSet = set;
  }
  return groups;
}
