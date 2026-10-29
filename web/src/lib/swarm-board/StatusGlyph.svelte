
<script lang="ts">
  import type { CardColumn } from './board-types';

  interface Props {
    column: CardColumn;
    size?: number;
    label?: string;
    plain?: boolean;
  }
  let { column, size = 14, label = '', plain = false }: Props = $props();
</script>

<svg class="sbg sbg--{column}" width={size} height={size} viewBox="0 0 14 14" role={label ? 'img' : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : 'true'}>
  {#if column === 'done' && plain}
    <path d="M2.5 7.4 L5.6 10.4 L11.5 3.8" class="sbg-check sbg-check--plain" />
  {:else if column === 'done'}
    <circle cx="7" cy="7" r="6" class="sbg-fill" />
    <path d="M4.3 7.2 L6.2 9 L9.8 5.2" class="sbg-check" />
  {:else}
    <circle cx="7" cy="7" r="5.5" class="sbg-ring" />
    {#if column === 'in_progress'}<path d="M7 3.5 A3.5 3.5 0 0 1 7 10.5 Z" class="sbg-half" />{/if}
    {#if column === 'review'}<circle cx="7" cy="7" r="2.2" class="sbg-ring" />{/if}
  {/if}
</svg>

<style>
  @layer components {
    .sbg {
      flex: none;
      --_c: var(--oc-text-secondary);
    }
    .sbg--in_progress { --_c: var(--oc-yellow); }
    .sbg--review { --_c: var(--oc-cyan); }
    .sbg--done { --_c: var(--oc-green); }
    .sbg-ring {
      fill: none;
      stroke: var(--_c);
      stroke-width: 1.5;
    }
    .sbg-half,
    .sbg-fill {
      fill: var(--_c);
    }
    .sbg-check {
      fill: none;
      stroke: var(--oc-ground-page);
      stroke-width: 1.5;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .sbg-check--plain {
      stroke: var(--_c);
      stroke-width: 2;
    }
  }
</style>
