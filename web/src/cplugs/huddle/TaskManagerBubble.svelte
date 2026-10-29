<script lang="ts">
  /* the markdown body */
  import type { Snippet } from 'svelte';
  import { Icon } from '../sdk/ui';
  import { providerMark, t } from '../sdk';
  import { messageTime } from './huddle-model';
  import { BUBBLES, type BubbleKind } from './task-manager-bubbles';
  import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
  import './task-manager-bubble.css';

  interface Props {
    kind: BubbleKind;
    tag?: 'li' | 'div' | 'article';
    layout?: 'row' | 'thread';
    header?: boolean;
    author?: string | null;
    time?: number | null;
    text?: string;
    limit?: number;
    more?: boolean;
    waiting?: boolean;
    cls?: string;
    lead?: Snippet;
    head?: Snippet;
    body?: Snippet;
    after?: Snippet;
    [attr: string]: unknown;
  }

  let { kind, tag = 'div', layout = 'row', header = undefined, author = null, time = null, text = '', limit = 0, more = false,
        waiting = false, cls = '', lead, head, body, after, ...rest }: Props = $props();

  const variant = $derived(BUBBLES[kind]);
  const showHead = $derived(header ?? layout === 'thread');
  const claudeMark = $derived(providerMark('claude', 12));
</script>

{#snippet inner()}
  {#if showHead}
    <span class="hb-head" data-hb-head>
      {#if author}
        <span class="hb-who" data-hb-who>
          {#if author === 'claude'}{@html claudeMark.svg}{:else}<Icon name="person-bust" size={14} />{/if}
          <span class="hb-name">{t(author === 'claude' ? 'cplug.huddle.thread.claude' : 'cplug.huddle.thread.joe')}</span>
        </span>
      {/if}
      {#if variant.labelKey}<span class="hb-kind" data-hb-kind={kind} title={variant.titleKey ? t(variant.titleKey) : undefined}>{t(variant.labelKey)}</span>{/if}
      {@render head?.()}
      {#if time !== null}<time class="hb-time" datetime={new Date(time * 1000).toISOString()}>{messageTime(time)}</time>{/if}
    </span>
  {/if}
  {#if body}{@render body()}{:else if text}<div class="hb-body" data-hb-body><TaskManagerMarkdown {text} {limit} {more} /></div>{/if}
{/snippet}

<svelte:element this={tag} class="hb hb--{layout} hb--{kind} {cls}" class:hb--waiting={waiting}
                style:--_post={variant.tone.color} style:--_post-hover={variant.tone.colorBright} data-hb={kind} {...rest}>
  {#if layout === 'row'}
    {#if lead}{@render lead()}{:else}<span class="hb-mark" aria-hidden="true"><Icon name={variant.icon} size={12} strokeWidth={1.75} /></span>{/if}
    <div class="hb-main">{@render inner()}</div>
  {:else}
    {@render inner()}
  {/if}
  {@render after?.()}
</svelte:element>
