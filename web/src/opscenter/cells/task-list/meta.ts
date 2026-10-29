import { metaFor } from '../../engine/meta';
import { listCount } from './state.svelte';
import './placement';

export const meta = metaFor('task-list');

export function titleCount(): number | null {
  return listCount();
}

export function phoneTotal(): number | null {
  return titleCount();
}
