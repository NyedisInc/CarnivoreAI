
<script lang="ts">
    import IconButton from '../../lib/base/IconButton.svelte';
    import { t } from '../../lib/i18n/index.svelte';
    import { layoutActive, layoutMode, memberForRow } from './mode.svelte';
    import { broadcastOn, toggleBroadcast } from './broadcast.svelte';
    import { layoutSearch } from './layout-search.svelte';
    import { rowIdForSession } from './names';

    let { sessionId }: { sessionId: string } = $props();

    const rowId = $derived(rowIdForSession(sessionId));
    const member = $derived(layoutActive() && !layoutMode.naming ? memberForRow(rowId) : null);
    const on = $derived(member ? broadcastOn(member) : true);
    const count = $derived(member && layoutSearch.query ? layoutSearch.countFor(member.session_row_id) : null);
    const current = $derived(member !== null && layoutSearch.current === member.session_row_id);
    let refused = $state('');

    async function flip(): Promise<void> {
        if (!member) return;
        refused = (await toggleBroadcast(member)) ?? '';
    }
</script>

{#if member}
    <span class="lcm" data-layout-cell={member.session_row_id}>
        {#if layoutSearch.query}
            <span class="lcm__count" class:lcm__count--current={current} data-layout-count={count ?? ''}>{count ?? '-'}</span>
        {/if}
        <IconButton label={refused ? t('layout.broadcast.failed', { reason: refused }) : on ? t('layout.broadcast.on') : t('layout.broadcast.off')}
            variant="quiet" pressed={on} iconSize={15} icon="chevron-right" data-broadcast-toggle={member.session_row_id}
            onclick={() => void flip()} />
    </span>
{/if}

<style>
  @layer components {
      .lcm {
          display: flex;
          align-items: center;
          gap: 2px;
          flex: none;
      }

      :global(.oc-frame-strip) .lcm {
          align-self: stretch;
          box-sizing: border-box;
          border-bottom: calc(var(--oc-border) + 5px) solid transparent;
      }

      :global(.oc-frame-strip) .lcm > :global([data-broadcast-toggle]) {
          width: 26px;
          height: 100%;
      }

      .lcm__count {
          min-width: 18px;
          padding: 1px 5px;
          border: 1px solid var(--oc-line-panel);
          border-radius: 3px;
          color: var(--oc-text-secondary);
          font-family: var(--font-mono);
          font-size: var(--oc-fs-micro, var(--oc-fs-micro));
          letter-spacing: var(--oc-tracking-label, 0.6px);
          text-align: center;
      }

      .lcm__count--current {
          border-color: var(--oc-orange);
          color: var(--oc-orange);
      }
  }
</style>
