<script lang="ts">
  import { renderMarkdown, t } from '../sdk';
  import { clockTime, laneColor, type FeedItem, type FeedLane } from './flow-model';

  interface Props {
    item: FeedItem;
    lane: FeedLane | undefined;
  }

  let { item, lane }: Props = $props();

  const FOLD = 600;
  let open = $state(false);
  const text = $derived(item.text ?? '');
  const long = $derived(text.length > FOLD);
  const owner = $derived(item.role === 'prompt');
  const shown = $derived(long && !open ? `${text.slice(0, FOLD)}...` : text);
  let host = $state<HTMLElement | null>(null);

  $effect(() => {
    if (host) host.replaceChildren(renderMarkdown(shown, host.ownerDocument));
  });
</script>

<div class="flw-bubble" class:flw-bubble--owner={owner} style:--_agent={laneColor(lane?.color ?? null)} data-flow-bubble={item.role}>
  <div class="flw-who">
    <span class="flw-name">{owner ? t('cplug.flow.chat.owner_to', { name: lane?.label ?? item.lane }) : (lane?.label ?? item.lane)}</span>
    {#if item.role === 'task'}<span class="flw-chip">{t('cplug.flow.chat.role.task')}</span>{/if}
    <time class="flw-time" datetime={new Date(item.t * 1000).toISOString()}>{clockTime(item.t)}</time>
  </div>
  <div class="flw-text flw-md" bind:this={host}></div>
  {#if long}
    <button type="button" class="flw-more" aria-expanded={open} onclick={() => (open = !open)}>
      {t(open ? 'cplug.flow.chat.less' : 'cplug.flow.chat.more')}
    </button>
  {/if}
</div>
