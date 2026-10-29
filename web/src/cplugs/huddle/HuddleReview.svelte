<script lang="ts">
  import { Icon } from '../sdk/ui';
  import { t } from '../sdk';
  import TaskManagerBubble from './TaskManagerBubble.svelte';
  import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
  import TaskManagerActionTag from './TaskManagerActionTag.svelte';
  import { followHash, linkTarget, type ReviewAnswer, type ReviewBlock } from './huddle-review';
  import { reviewOpen, setReviewOpen } from './task-manager-review-fold';
  import { mdPlain } from './task-manager-markdown';
  import { issueNumber } from './task-manager-github-issue';

  let { block, id, answer = null, issue = null, foldAll = false, unfolded = false }: { block: ReviewBlock; id: number; answer?: ReviewAnswer | null; issue?: string | null; foldAll?: boolean; unfolded?: boolean } = $props();

  const linkIssue = $derived(block.link && issue === block.link ? issueNumber(block.link) : null);

  const target = $derived(block.link ? linkTarget(block.link, window.location) : null);
  let open = $state(foldAll ? unfolded : reviewOpen(id));
  const foldable = $derived(foldAll ? !!block.summary : block.hasMore);
  let answerOpen = $state(false);

  function toggle(): void {
    open = !open;
    if (!foldAll) setReviewOpen(id, open);
  }

  function onSection(event: MouseEvent): void {
    if (!foldable) return;
    if ((event.target as Element | null)?.closest('a, [data-task-manager-command]')) return;
    if (window.getSelection()?.toString()) return;
    toggle();
  }

  function descriptionTip(node: HTMLElement, tip: string | null): { update: (next: string | null) => void } {
    const apply = (next: string | null): void => {
      if (next) node.setAttribute('data-tooltip', next);
      else node.removeAttribute('data-tooltip');
    };
    apply(tip);
    return { update: apply };
  }

  function onLink(event: MouseEvent): void {
    if (target?.hash) {
      event.preventDefault();
      followHash(target.hash);
    }
  }
</script>

<div class="tkm-review" data-task-manager-review-wrap={id}>
  <TaskManagerBubble kind="review" header data-task-manager-review={id}>
    {#snippet body()}
      {#if block.summary}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="tkm-review-part tkm-review-summary" class:tkm-review-click={foldable} data-task-manager-review-summary
             use:descriptionTip={foldable && !open ? mdPlain(block.description) : null} onclick={onSection}>
          {#if foldable}
            <button type="button" class="tkm-review-fold" aria-expanded={open} data-task-manager-review-fold
                    title={t(open ? 'cplug.huddle.review.hide' : 'cplug.huddle.review.show')}
                    aria-label={t(open ? 'cplug.huddle.review.hide' : 'cplug.huddle.review.show')}>
              <Icon name={open ? 'chevron-down' : 'chevron-right'} size={10} />
            </button>
          {/if}
          <span class="tkm-review-line" class:tkm-review-line--one={foldAll && !open}>{block.summary}</span>
        </div>
        {#if block.hasMore && open}
          <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
          <div class="hb-body tkm-review-part tkm-review-text tkm-review-click" data-task-manager-review-description onclick={onSection}><TaskManagerMarkdown text={block.description} /></div>
        {/if}
      {/if}
      {#if !foldAll || open || !block.summary}
      <div class="tkm-review-part tkm-review-todo" data-task-manager-review-part>
        <span class="tkm-review-key">{t('cplug.huddle.review.part')}</span>
        <TaskManagerActionTag action={block.action} {id} />
        {#if block.where}<span class="tkm-review-path" data-task-manager-review-where>{block.where}</span>{/if}
        {#if target}
          <a class="tkm-review-link" href={target.href} data-task-manager-review-link data-link-kind={target.kind}
             target={target.hash ? undefined : '_blank'} rel={target.hash ? undefined : 'noopener'} onclick={onLink}>{linkIssue ? t('cplug.huddle.review.open_issue', { number: linkIssue }) : t('cplug.huddle.review.open')}</a>
        {/if}
      </div>
      {/if}
    {/snippet}
  </TaskManagerBubble>
  {#if answer}
    <div class="tkm-review-answer" data-task-manager-review-answer={answer.id}>
      <span class="tkm-review-key">{t('cplug.huddle.review.answered')}</span>
      {#if answerOpen}
        <div class="tkm-review-answer-text"><TaskManagerMarkdown text={answer.text} /></div>
      {:else}
        <span class="tkm-review-line">{answer.summary}</span>
      {/if}
      {#if answer.hasMore}
        <button type="button" class="tkm-review-more" aria-expanded={answerOpen} data-task-manager-review-answer-more
                onclick={() => (answerOpen = !answerOpen)}>{t(answerOpen ? 'cplug.huddle.review.less' : 'cplug.huddle.review.more')}</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  @layer components {
    :global(.hdr > .tkm-review) {
      grid-column: 4 / 6;
      grid-row: 3;
      margin-top: 4px;
      margin-left: calc(-1 * var(--hdr-lead, 0px));
      min-width: 0;
    }

    @container hdr (max-width: 22rem) {
      :global(.hdr > .tkm-review) {
        grid-column: 1 / -1;
        margin-left: 0;
      }
    }

    .tkm-review-part + .tkm-review-part {
      margin-top: 4px;
      padding-top: 4px;
      box-shadow: 0 -1px 0 var(--oc-line-rule);
    }

    .tkm-review-summary {
      display: flex;
      align-items: baseline;
      gap: var(--oc-space-2);
      min-width: 0;
    }

    .tkm-review-click {
      cursor: pointer;
    }

    .tkm-review-line {
      min-width: 0;
      color: var(--oc-text-primary);
      font-size: var(--hd-fs-body, var(--oc-fs-body));
      line-height: 1.5;
      overflow-wrap: anywhere;
    }

    .tkm-review-line--one {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .tkm-review-fold,
    .tkm-review-more {
      flex: none;
      padding: 0;
      border: 0;
      background: none;
      color: var(--oc-text-muted);
      font: inherit;
      cursor: pointer;
    }

    .tkm-review-more {
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .tkm-review-fold:hover,
    .tkm-review-more:hover {
      color: var(--oc-text-primary);
    }

    .tkm-review-todo {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 6px;
      color: var(--oc-text-secondary);
    }

    .tkm-review-answer {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 6px;
      margin-top: 4px;
      min-width: 0;
    }

    .tkm-review-answer-text {
      flex: 1 1 100%;
      min-width: 0;
      color: var(--oc-text-primary);
      font-size: var(--hd-fs-body, var(--oc-fs-body));
      line-height: 1.5;
    }

    .tkm-review-text {
      margin: 0;
      color: var(--oc-text-primary);
      font-size: var(--hd-fs-body, var(--oc-fs-body));
      line-height: 1.5;
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .tkm-review-key {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .tkm-review-path {
      min-width: 0;
      white-space: pre-wrap;
    }

    .tkm-review-link {
      color: var(--oc-cyan);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-decoration: none;
      text-transform: uppercase;
    }

    .tkm-review-link:hover {
      text-decoration: underline;
    }
  }
</style>
