import { metaFor } from '../../engine/meta';
import { contentsCount } from './state.svelte';
import './placement';

export const meta = metaFor('session-contents');

export function titleCount(): number | null {
  return contentsCount();
}

export function phoneTotal(): number | null {
  return titleCount();
}
