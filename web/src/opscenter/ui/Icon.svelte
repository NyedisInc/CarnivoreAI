<script lang="ts">
  import { icons, type SizedIcon } from './icons';

  let {
    name,
    size = 16,
    strokeWidth = 1.5,
    fill = 'outline',
  }: { name: string; size?: number; strokeWidth?: number; fill?: 'outline' | 'solid' } = $props();

  const solid = $derived(fill === 'solid');

  const entry = $derived<string | SizedIcon>(icons[name] ?? icons['grid'] ?? '');
  const path = $derived(typeof entry === 'string' ? entry : entry.path);
  const box = $derived(typeof entry === 'string' ? '0 0 24 24' : entry.viewBox);
</script>

<svg
  width={size}
  height={size}
  viewBox={box}
  fill={solid ? 'currentColor' : 'none'}
  stroke={solid ? 'none' : 'currentColor'}
  stroke-width={strokeWidth}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  focusable="false"
  data-icon={name}
>{@html path}</svg>
