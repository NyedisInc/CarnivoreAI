<script lang="ts">
  import { getContext } from 'svelte';
  import { Icon } from '../sdk/ui';
  import { BODY_OPTIONS, DEFAULT_BODY_OPTIONS, type BodyOptions } from './task-manager-body-options';
  import { providerMark, t } from '../sdk';
  import type { HuddleItem } from './huddle-model';
  import { isFormAnswer } from './task-manager-bubbles';
  import { latestMessage, type RowParts } from './huddle-density';
  import TaskManagerRowPosts from './TaskManagerRowPosts.svelte';
  import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
  import { mdPlain } from './task-manager-markdown';
  import TaskManagerForkedFrom from './TaskManagerForkedFrom.svelte';
  import TaskManagerFromProject from './TaskManagerFromProject.svelte';
  import TaskManagerProgress from './TaskManagerProgress.svelte';
  import TaskManagerSteps from './TaskManagerSteps.svelte';
  import { stepsOfItem } from './task-manager-steps.svelte';
  import { progressOf } from './task-manager-progress.svelte';

  let { item, parts }: { item: HuddleItem; parts: RowParts } = $props();

  const options: Readonly<BodyOptions> = getContext<BodyOptions | undefined>(BODY_OPTIONS) ?? DEFAULT_BODY_OPTIONS;
  const stroke = options.drawerIcons ? 2 : undefined;
  const last = $derived(parts.latest ? latestMessage(item) : null);
  const claudeMark = $derived(providerMark('claude', 12));
  const steps = $derived(stepsOfItem(item.list, item.id));
  const live = $derived(progressOf(item.id).length > 0 || steps !== null);
  const byLabel = $derived(last ? t(last.author === 'claude' ? 'cplug.huddle.thread.claude' : isFormAnswer(last) ? 'cplug.huddle.thread.form_answer' : 'cplug.huddle.thread.joe') : '');
</script>

{#if live || parts.description || last || parts.posts === 'block' || parts.questions || (parts.extras && (item.forked_from != null || item.from_project != null))}
  <div class="tkm-peek tkm-lead-host" data-task-manager-peek={item.id}>
    {#if parts.extras}<TaskManagerForkedFrom {item} /><TaskManagerFromProject {item} />{/if}
    <TaskManagerProgress id={item.id} />
    <TaskManagerSteps entry={steps} />
    {#if parts.description}<div class="tkm-peek-desc" data-task-manager-peek-description={item.id}><TaskManagerMarkdown text={item.text} /></div>{/if}
    {#if last}
      <p class="tkm-latest" class:tkm-latest--claude={last.author === 'claude'} data-task-manager-latest={item.id} data-by={last.author}
         data-kind={last.kind} title={mdPlain(last.text)}>
        <span class="tkm-latest-by" role="img" aria-label={byLabel} title={byLabel}>
          {#if last.author === 'claude'}{@html claudeMark.svg}{:else if isFormAnswer(last)}<Icon name="list" size={12} strokeWidth={stroke} />{:else}<Icon name="person-bust" size={12} strokeWidth={stroke} />{/if}
        </span>
        <span class="tkm-latest-text"><TaskManagerMarkdown text={last.text} inline /></span>
      </p>
    {/if}
    {#if parts.posts === 'block' || parts.questions}<TaskManagerRowPosts {item} {parts} />{/if}
  </div>
{/if}

<style>
  @layer components {
    .tkm-peek {
      grid-column: 4 / 6;
      grid-row: 2;
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
      margin-top: 2px;
    }

    @container hdr (max-width: 22rem) {
      .tkm-peek {
        grid-column: 1 / -1;
        --hdr-lead: 0px;
      }
    }

    .tkm-peek-desc {
      margin: 0;
      color: var(--oc-text-primary);
      font-size: var(--hd-fs-body, inherit);
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .tkm-latest {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      margin: 0;
      color: var(--oc-text-muted);
      line-height: 16px;
    }

    .tkm-latest-by {
      flex: none;
      display: inline-flex;
      align-items: center;
      width: 12px;
      height: 12px;
      color: var(--oc-text-muted);
    }

    .tkm-latest-by :global(svg) {
      width: 12px;
      height: 12px;
    }

    .tkm-latest--claude .tkm-latest-by {
      color: var(--oc-orange);
    }

    .tkm-latest-text {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
</style>
