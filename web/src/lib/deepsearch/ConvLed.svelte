<script lang="ts">
  import SessionFace from '../sessions/SessionFace.svelte';
  import type { ListingRow } from '../../cplugs/sdk/sessions.svelte';
  import type { LedKind } from './result-model';

  interface Props {
    kind: LedKind;
    live: ListingRow | undefined;
    title: string;
  }
  let { kind, live, title }: Props = $props();
</script>

{#if kind === 'live' && live}
  <SessionFace row={live} />
{:else}
  <span class="dps__led" class:dps__led--ring={kind !== 'dash'} class:dps__led--dash={kind === 'dash'} {title} role="img" aria-label={title}></span>
{/if}
