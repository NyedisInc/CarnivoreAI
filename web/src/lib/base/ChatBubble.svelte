<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import './chat-bubble.css';

  interface Props extends Omit<HTMLAttributes<HTMLElement>, 'class' | 'children' | 'title'> {
    kind: string;
    tone?: string;
    toneBright?: string;
    tag?: 'li' | 'div' | 'article';
    layout?: 'row' | 'thread';
    header?: boolean;
    headNowrap?: boolean;
    who?: Snippet;
    label?: string | null;
    labelTitle?: string;
    time?: number | null;
    timeText?: string;
    waiting?: boolean;
    owner?: boolean;
    cls?: string;
    mark?: Snippet;
    head?: Snippet;
    body?: Snippet;
    after?: Snippet;
  }

  let { kind, tone = undefined, toneBright = undefined, tag = 'div', layout = 'row', header = undefined, headNowrap = false, who, label = null,
        labelTitle = undefined, time = null, timeText = '', waiting = false, owner = false, cls = '', mark, head, body, after,
        ...rest }: Props = $props();

  const showHead = $derived(header ?? layout === 'thread');
</script>

{#snippet inner()}
  {#if showHead}
    <span class="hb-head" data-hb-head>
      {#if who}<span class="hb-who" data-hb-who>{@render who()}</span>{/if}
      {#if label}<span class="hb-kind" data-hb-kind={kind} title={labelTitle}>{label}</span>{/if}
      {@render head?.()}
      {#if time !== null}<time class="hb-time" datetime={new Date(time * 1000).toISOString()}>{timeText}</time>{/if}
    </span>
  {/if}
  {@render body?.()}
{/snippet}

<svelte:element this={tag} class="hb hb--{layout} hb-k--{kind} {cls}" class:hb--waiting={waiting} class:hb--owner-side={owner} class:hb--head-nowrap={headNowrap}
                style:--_post={tone} style:--_post-hover={toneBright} data-hb={kind} {...rest}>
  {#if layout === 'row'}
    <span class="hb-mark">{@render mark?.()}</span>
    <div class="hb-main">{@render inner()}</div>
  {:else}
    {@render inner()}
  {/if}
  {@render after?.()}
</svelte:element>
