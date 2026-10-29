import type { StatusHue } from '../api/sessions.svelte';

export function hueDotToken(hue: StatusHue): string {
  switch (hue) {
    case 'green':
      return 'var(--oc-green-bright)';
    case 'yellow':
      return 'var(--oc-yellow-bright)';
    case 'blue':
      return 'var(--oc-cyan)';
    case 'red':
      return 'var(--oc-coral)';
    default:
      return 'var(--oc-text-dim)';
  }
}

export function hueLabelToken(hue: StatusHue): string {
  switch (hue) {
    case 'green':
      return 'var(--oc-green)';
    case 'yellow':
      return 'var(--oc-yellow)';
    case 'blue':
      return 'var(--oc-cyan)';
    case 'red':
      return 'var(--oc-coral)';
    default:
      return 'var(--oc-text-dim)';
  }
}
