<script lang="ts">
  /* the markdown body */
  import type { Snippet } from 'svelte';
  import { ChatBubble, Icon } from '../sdk/ui';
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
  const claudeMark = $derived(providerMark('claude', 12));
</script>

{#snippet who()}
  {#if author === 'claude'}{@html claudeMark.svg}{:else}<Icon name="person-bust" size={14} />{/if}
  <span class="hb-name">{t(author === 'claude' ? 'cplug.huddle.thread.claude' : 'cplug.huddle.thread.joe')}</span>
{/snippet}

{#snippet defaultBody()}
  {#if body}{@render body()}{:else if text}<div class="hb-body" data-hb-body><TaskManagerMarkdown {text} {limit} {more} /></div>{/if}
{/snippet}

{#snippet markIcon()}<span aria-hidden="true"><Icon name={variant.icon} size={12} strokeWidth={1.75} /></span>{/snippet}

<ChatBubble {kind} {tag} {layout} {header} {waiting} {cls} tone={variant.tone.color} toneBright={variant.tone.colorBright}
            who={author ? who : undefined} label={variant.labelKey ? t(variant.labelKey) : null}
            labelTitle={variant.titleKey ? t(variant.titleKey) : undefined} {time} timeText={time !== null ? messageTime(time) : ''}
            owner={kind === 'owner'} mark={lead ?? markIcon} {head} body={defaultBody} {after} {...rest} />
