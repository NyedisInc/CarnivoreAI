<script lang="ts">
  import { t } from '../sdk';
  import { clockTime, laneColor, shortDuration, type FeedItem, type FeedLane } from './flow-model';

  interface Props {
    item: FeedItem;
    lanes: Map<string, FeedLane>;
  }

  let { item, lanes }: Props = $props();

  let open = $state(false);
  const from = $derived(lanes.get(item.lane));
  const to = $derived(item.to ? lanes.get(item.to) : undefined);
  const tally = $derived(Object.entries(item.tools ?? {}).slice(0, 4).map(([tool, n]) => `${tool} ${n}`).join('  '));
  const crosstalkState = $derived(item.landed ? 'landed' : item.delivered ? 'delivered' : 'queued');
</script>

{#snippet who(lane: FeedLane | undefined, fallback: string)}
  <span class="flw-name" style:--_agent={laneColor(lane?.color ?? null)}>{lane?.label ?? fallback}</span>
{/snippet}

<div class="flw-card" data-kind={item.kind} data-flow-card={item.kind}>
  <div class="flw-who">
    <span class="flw-kind">{t(`cplug.flow.chat.kind.${item.kind}`)}</span>
    <span class="flw-route">
      {@render who(from, item.lane)}
      {#if item.to}<span aria-hidden="true">&gt;</span>{@render who(to, item.to)}{/if}
    </span>
    <time class="flw-time" datetime={new Date(item.t * 1000).toISOString()}>{clockTime(item.t)}</time>
  </div>

  {#if item.kind === 'work'}
    <div class="flw-meta">
      <span>{t('cplug.flow.chat.work.calls', { count: item.count ?? 0 })}</span>
      <span>{shortDuration(item.duration_s ?? 0)}</span>
      <span>{tally}</span>
      <button type="button" class="flw-more" aria-expanded={open} onclick={() => (open = !open)}>
        {t(open ? 'cplug.flow.chat.less' : 'cplug.flow.chat.more')}
      </button>
    </div>
    {#if open}
      <ul class="flw-calls">
        {#each item.calls ?? [] as call, n (n)}
          <li class="flw-call">
            <span class="flw-call-tool">{call.tool}</span>
            <span>{shortDuration(call.end - call.start)}</span>
            <time datetime={new Date(call.start * 1000).toISOString()}>{clockTime(call.start)}</time>
          </li>
        {/each}
      </ul>
    {/if}
  {:else}
    {#if item.label && !(item.kind === 'task' && item.change === 'moved')}<p class="flw-text">{item.label}</p>{/if}
    <div class="flw-meta">
      {#if item.kind === 'crosstalk'}
        <span>{t(`cplug.flow.chat.crosstalk.${crosstalkState}`)}</span>
        {#if item.thread}<span>{t('cplug.flow.chat.crosstalk.thread', { thread: item.thread })}</span>{/if}
        {#if item.reply_to}<span>{t('cplug.flow.chat.crosstalk.reply')}</span>{/if}
      {:else if item.kind === 'return'}
        {#if item.duration_s !== null && item.duration_s !== undefined}<span>{shortDuration(item.duration_s)}</span>{/if}
        {#if item.tool_count !== null && item.tool_count !== undefined}<span>{t('cplug.flow.chat.work.calls', { count: item.tool_count })}</span>{/if}
      {:else if item.kind === 'spawn' && item.basis}
        <span>{t('cplug.flow.chat.spawn.basis', { basis: item.basis })}</span>
      {:else if item.kind === 'task'}
        {#if item.item_id}<span>{t('cplug.flow.chat.task.item', { id: String(item.item_id) })}</span>{/if}
        {#if item.change === 'moved'}<span>{t('cplug.flow.chat.task.moved', { from: item.from_col ?? '', to: item.to_col ?? '' })}</span>
        {:else}<span>{t('cplug.flow.chat.task.filed')}</span>{/if}
      {:else if item.kind === 'huddle'}
        {#if item.owner}<span>{t('cplug.flow.chat.huddle.owner')}</span>{/if}
      {/if}
      {#if item.inferred}<span class="flw-meta--warn">{t('cplug.flow.chat.inferred')}</span>{/if}
    </div>
  {/if}
</div>
