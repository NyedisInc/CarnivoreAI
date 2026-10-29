
import { metaFor } from '../../engine/meta';
import { questionCount } from './state.svelte';
import './placement';

export const meta = metaFor('questions');

export function titleCount(): number | null {
  return questionCount();
}

export function phoneTotal(): number | null {
  return titleCount();
}
