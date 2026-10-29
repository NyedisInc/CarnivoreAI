<script lang="ts">
  import { tick } from 'svelte';
  import { buttonAttrs } from '../../../lib/base/classes';
  import { titleWhenTruncated } from '../../../lib/base/truncate';
  import { t } from '../../../lib/i18n/index.svelte';
  import Icon from '../../ui/Icon.svelte';
  import TaskManagerMarkdown from '../../../cplugs/huddle/TaskManagerMarkdown.svelte';
  import type { Inspection, Task } from '../../../cplugs/huddle/task-manager-design/model';
  import { anchorOf, restoreAnchor } from '../../../cplugs/huddle/task-manager-design/scroll-anchor';
  import { unread } from '../../../cplugs/huddle/task-manager-design/unread';

  let { task, view, onResource, source = -1, detailed = false }: { task: Task; view: Inspection; onResource: (id: string) => void; source?: number; detailed?: boolean } = $props();

  let chat: HTMLDivElement | undefined = $state();

  async function toggleEarlier(): Promise<void> {
    const anchor = chat ? anchorOf(chat) : null;
    view.earlier = !view.earlier;
    await tick();
    if (chat && anchor) restoreAnchor(chat, anchor);
  }

  const boundary = $derived(view.boundary);
  const start = $derived(view.earlier || source >= 0 ? 0 : boundary >= 0 ? boundary : Math.max(0, task.messages.length - 3));

  $effect(() => {
    const id = task.id;
    const located = source;
    void tick().then(() => {
      if (chat) { if (located >= 0) chat.querySelector(`[data-message-index="${located}"]`)?.scrollIntoView({ block: 'nearest' }); else chat.scrollTop = view.scroll; }
    });
    return () => { void id; };
  });
</script>

{#if start > 0 || view.earlier}
  <button type="button" class="tn-history-toggle" use:titleWhenTruncated {...buttonAttrs('secondary', 'sm')} data-task-manager-earlier onclick={() => void toggleEarlier()}>
    {view.earlier ? t('opscenter.cell.task_manager_mk2.hide_read') : t('opscenter.cell.task_manager_mk2.show_read', { n: start })}
  </button>
{/if}
<div class="tn-chat" class:tn-chat--tall={detailed} role="region" aria-label={t('cplug.huddle.tm.conversation_for', { title: task.title })} tabindex="0" bind:this={chat} onscroll={() => { if (chat) view.scroll = chat.scrollTop; }}>
  {#each task.messages as message, index}
    {#if index >= start}
      {#if index === boundary}<div class="tn-newline" data-task-manager-new-line>{t('cplug.huddle.tm.new_messages_line')}</div>{/if}
      {#if message.system}
        <div class="tn-status-line" data-message-index={index} data-mk2-status-line>{message.text}<time>{message.time}</time></div>
      {:else if message.event}
        <div class="tn-history-event" data-message-index={index}>{message.text} <time>{message.time}</time></div>
      {:else}
        <article class:owner={message.by === 'you'} class:new={message.by === 'agent' && !message.read} class:located={source === index} class="tn-message" data-message-index={index}>
          <div class="tn-message-top"><strong>{message.by === 'you' ? t('cplug.huddle.tm.you') : task.agent}</strong>
            {#if message.by === 'agent'}<span class="tn-subtle">{t('cplug.huddle.tm.agent_role')}</span>{/if}
            {#if message.kind === 'question'}<span class="ask"><Icon name="help" size={12} strokeWidth={2} />{t('cplug.huddle.tm.question')}</span>{:else if message.comment}<span class="tn-subtle">{t('cplug.huddle.tm.comment')}</span>{/if}
            <time>{message.time}</time>
            {#if message.by === 'agent' && !message.read}<span class="tm-new-mark">{t('cplug.huddle.tm.new')}</span>{/if}
          </div>
          {#if message.quote}<blockquote>{message.quote}</blockquote>{/if}
          <div class="tn-md"><TaskManagerMarkdown text={message.text} /></div>
          {#each message.sharedIds ?? [] as id}
            {@const resource = task.shared?.find(r => r.id === id)}
            {#if resource}<button type="button" class="tn-resource" use:titleWhenTruncated {...buttonAttrs('secondary', 'sm')} onclick={() => onResource(id)}><Icon name={resource.type === 'image' ? 'image' : 'docs'} size={12} strokeWidth={2} />{resource.name}</button>{/if}
          {/each}
        </article>
      {/if}
    {/if}
  {/each}
  {#if task.messages.length === 0}<p class="tn-empty">{t('cplug.huddle.tm.no_messages')}</p>{/if}
</div>
{#if !unread(task)}<p class="tn-subtle">{t('cplug.huddle.tm.caught_up_reading')}</p>{/if}
