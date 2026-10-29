
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import type { BoardData } from './board-data.svelte';
  import type { CardView } from './board-types';
  import {
    archiveCall, autoPromoteCall, collapsed, columnCall, isWaiting, moveCall, runCalls, stageActions, toggleCollapsed, type CardAction,
  } from './card-actions.svelte';

  interface Props {
    card: CardView;
    data: BoardData;
    mode?: 'reclassify' | 'delete' | null;
    only?: readonly CardAction[];
  }
  let { card, data, mode = $bindable(null), only }: Props = $props();

  let busy = $state(false);
  const actions = $derived(stageActions(card).filter((a) => !only || only.includes(a)));
  const folded = $derived(collapsed.ids.includes(card.id));

  const ICON: Record<CardAction, string> = {
    top: 'to-top', bottom: 'to-bottom', pause: 'pause', done: 'check', promote: 'arrow-up-circle', reclassify: 'cycle',
    archive: 'archive', collapse: 'shrink', delete: 'trash',
  };

  function tip(action: CardAction): string {
    if (action === 'promote') return t(card.auto_promote ? 'swarm.board.act.promote.on' : 'swarm.board.act.promote.off');
    if (action === 'archive' && card.archived_at !== null) return t('swarm.board.act.unarchive');
    if (action === 'collapse' && folded) return t('swarm.board.act.expand');
    return t(`swarm.board.act.${action}`);
  }

  async function act(action: CardAction): Promise<void> {
    const id = card.id;
    if (action === 'collapse') return toggleCollapsed(id);
    if (action === 'reclassify' || action === 'delete') {
      mode = mode === action ? null : action;
      return;
    }
    const fail = (error: string) => t('swarm.board.act.error', { error });
    const plan: Partial<Record<CardAction, [ReturnType<typeof moveCall>, string]>> = {
      top: [moveCall(id, firstWaitingOther()), t('swarm.board.act.ok.top', { id })],
      bottom: [moveCall(id, null), t('swarm.board.act.ok.bottom', { id })],
      pause: [columnCall(id, 'todo'), t('swarm.board.act.ok.pause', { id })],
      done: [columnCall(id, 'done'), t('swarm.board.act.ok.done', { id })],
      promote: [autoPromoteCall(id, !card.auto_promote), t(card.auto_promote ? 'swarm.board.act.ok.promote_off' : 'swarm.board.act.ok.promote_on', { id })],
      archive: [archiveCall(id, card.archived_at === null), t(card.archived_at === null ? 'swarm.board.act.ok.archive' : 'swarm.board.act.ok.unarchive', { id })],
    };
    const step = plan[action];
    if (!step) return;
    busy = true;
    try {
      await runCalls([step[0]], step[1], data.refresh, fail);
    } finally {
      busy = false;
    }
  }

  function firstWaitingOther(): number | null {
    for (const lane of data.board?.lanes ?? []) {
      if (lane.list_key !== card.list_key) continue;
      const first = (lane.columns[card.column] ?? []).find((c) => c.list_key === card.list_key && isWaiting(c));
      return first && first.id !== card.id ? first.id : null;
    }
    return null;
  }
</script>

<span class="sba" role="group" aria-label={t('swarm.board.actions', { id: card.id })} data-swarm-card-actions={card.id}>
  {#each actions as action (action)}
    {@const pressed = action === 'promote' ? card.auto_promote : action === 'reclassify' || action === 'delete' ? mode === action : undefined}
    <button type="button" class="oc-ibtn oc-ibtn--bare sba-key" class:sba-key--on={action === 'promote' && card.auto_promote} class:sba-key--danger={action === 'delete'}
            title={tip(action)} aria-label={tip(action)} aria-pressed={pressed} disabled={busy || (action === 'top' && firstWaitingOther() === null)}
            data-swarm-card-act={action} onclick={(e) => { e.stopPropagation(); void act(action); }}>
      <Icon name={action === 'collapse' && folded ? 'expand' : ICON[action]} size={14} />
    </button>
  {/each}
</span>

<style>
  @layer components {
    .sba {
      display: inline-flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 2px;
    }
    .sba-key {
      --oc-ibtn-size: 24px;
    }
    .sba-key--on {
      color: var(--oc-green);
    }
    .sba-key--danger:hover:not(:disabled) {
      border-color: var(--oc-coral);
      color: var(--oc-coral);
    }
  }
</style>
