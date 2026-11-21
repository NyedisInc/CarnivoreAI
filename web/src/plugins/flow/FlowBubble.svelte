<script lang="ts">
  import { renderMarkdown, t } from '../sdk';
  import { Button, ChatBubble } from '../sdk/ui';
  import './flow.css';
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
  const ROLES = ['agent', 'prompt', 'task'] as const;
  type Role = (typeof ROLES)[number];
  const isRole = (r: string | null | undefined): r is Role => ROLES.some((known) => known === r);
  const role: Role = $derived(isRole(item.role) ? item.role : 'agent');
  const owner = $derived(role === 'prompt');
  const shown = $derived(long && !open ? `${text.slice(0, FOLD)}...` : text);
  const agentColor = $derived(laneColor(lane?.color ?? null));
  let host = $state<HTMLElement | null>(null);

  $effect(() => {
    if (host) host.replaceChildren(renderMarkdown(shown, host.ownerDocument));
  });
</script>

{#snippet who()}
  <span class="flw-name">{owner ? t('cplug.flow.chat.owner_to', { name: lane?.label ?? item.lane }) : (lane?.label ?? item.lane)}</span>
{/snippet}

{#snippet body()}
  <div>
    <div class="flw-text flw-md" bind:this={host}></div>
    {#if long}
      <Button variant="quiet" size="sm" data-flow-more aria-expanded={open} onclick={() => (open = !open)}>
        {t(open ? 'cplug.flow.chat.less' : 'cplug.flow.chat.more')}
      </Button>
    {/if}
  </div>
{/snippet}

<ChatBubble kind={role} layout="thread" headNowrap {owner} tone={agentColor} label={role === 'task' ? t('cplug.flow.chat.role.task') : null} time={item.t} timeText={clockTime(item.t)}
            cls="flw-bubble" data-flow-bubble={role} {who} {body} />
