
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { RUN_MARKS, runMarkName } from './logic/marks';
  import { statusWord } from './logic/words';

  type Props = { status?: string; light?: 'ok' | 'off'; size?: number; label?: string };
  let { status, light, size = 10, label }: Props = $props();

  const name = $derived(runMarkName(status ?? ''));
  const words = $derived(label ?? (light ? t(light === 'ok' ? 'automations.page.row.on' : 'automations.page.row.off') : statusWord(name)));
</script>

{#if light}
  <svg class="ap-mk-light" data-kind={light} width={size} height={size} viewBox="0 0 14 14" role="img" aria-label={words}>
    {#if light === 'off'}<circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5" />{:else}<circle cx="7" cy="7" r="5" fill="currentColor" />{/if}
  </svg>
{:else}
  <svg class="ap-mk-run" data-status={name} width={size} height={size} viewBox="0 0 14 14" role="img" aria-label={words}>
    {#each RUN_MARKS[name] as part, i (i)}<svelte:element this={part.tag} {...part.attrs} />{/each}
  </svg>
{/if}
