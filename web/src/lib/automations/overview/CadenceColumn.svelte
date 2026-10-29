
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import State from '../../base/State.svelte';
  import type { Automation } from '../api';
  import type { UnreadState } from '../logic/feed';
  import AutoCard from './AutoCard.svelte';
  import { capped, GROUP_CAP } from './overview-model';
  import { overview } from './overview-state.svelte';

  let { id, rows, unread }: { id: 'often' | 'slow'; rows: readonly Automation[]; unread: UnreadState } = $props();

  const open = $derived(!!overview.expanded[id]);
  const shown = $derived(capped(rows, open));
</script>

<section class="t-col s-group" data-col={id}>
  <div class="s-group__h">
    <span class="pl-label">{t(`automations.simple.col.${id}`)}</span>
    <span class="ap-num">{rows.length}</span>
    <span class="t-quiet">{t(`automations.simple.col.${id}_line`)}</span>
  </div>
  {#if rows.length}
    <div class="s-cards">
      {#each shown as a (a.automation_id)}<AutoCard automation={a} {unread} />{/each}
    </div>
  {:else}
    <State title={t('automations.simple.col.empty')} inline />
  {/if}
  {#if rows.length > GROUP_CAP}
    <Button size="sm" data-more={id} onclick={() => (overview.expanded = { ...overview.expanded, [id]: !open })}>
      {open ? t('automations.simple.col.show_fewer') : t('automations.simple.col.show_all', { n: rows.length })}
    </Button>
  {/if}
</section>
