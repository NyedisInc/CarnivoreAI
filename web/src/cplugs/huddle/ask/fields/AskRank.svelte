<script lang="ts">
  import { Button, Icon } from '../../../sdk/ui';
  import { t } from '../../../sdk';
  import { moveInOrder, startingOrder, type AskQuestion, type AskValue } from '../ask-model';
  import TaskManagerMarkdown from '../../TaskManagerMarkdown.svelte';
  import { mdPlain } from '../../task-manager-markdown';

  let { question, value, onChange }: { question: AskQuestion; value: AskValue | undefined; onChange: (patch: AskValue) => void } = $props();
  const order = $derived(value?.order ?? startingOrder(question));
  const label = (id: string): string => (question.options ?? []).find((o) => o.id === id)?.label ?? id;
  const same = $derived(question.recommend?.order !== undefined && JSON.stringify(order) === JSON.stringify(question.recommend.order));
  let grabbed = $state<{ id: string; from: string[] } | null>(null);

  function move(id: string, by: -1 | 1, root: HTMLElement): void {
    onChange({ order: moveInOrder(order, id, by), touched: true });
    queueMicrotask(() => root.querySelector<HTMLElement>(`[data-ask-row="${id}"]`)?.focus());
  }

  function onKeydown(event: KeyboardEvent, id: string): void {
    const root = event.currentTarget as HTMLElement;
    const list = root.parentElement as HTMLElement;
    if ((event.key === 'ArrowUp' || event.key === 'ArrowDown') && event.altKey) {
      event.preventDefault();
      move(id, event.key === 'ArrowUp' ? -1 : 1, list);
    } else if ((event.key === 'ArrowUp' || event.key === 'ArrowDown') && grabbed?.id === id) {
      event.preventDefault();
      move(id, event.key === 'ArrowUp' ? -1 : 1, list);
    } else if (event.key === ' ' && event.target === root) {
      event.preventDefault();
      grabbed = grabbed?.id === id ? null : { id, from: [...order] };
    } else if (event.key === 'Escape' && grabbed) {
      event.preventDefault();
      event.stopPropagation();
      onChange({ order: grabbed.from });
      grabbed = null;
    }
  }
</script>

<ol class="hdq-rank" role="listbox" aria-label={mdPlain(question.prompt)} aria-orientation="vertical" data-ask-field={question.id}>
  {#each order as id, at (id)}
    <li role="option" tabindex="0" aria-selected={grabbed?.id === id} data-grabbed={grabbed?.id === id ? "true" : undefined} aria-label={`${at + 1}. ${mdPlain(label(id))}`} data-ask-row={id}
        onkeydown={(event) => onKeydown(event, id)} onblur={() => { if (grabbed?.id === id) grabbed = null; }}>
      <span class="hdq-pos">{at + 1}</span>
      <span class="hdq-rank-label"><TaskManagerMarkdown text={label(id)} inline /></span>
      <span class="hdq-moves">
        <button type="button" class="oc-ibtn" aria-label={t('cplug.huddle.ask.move_up')} disabled={at === 0}
                data-ask-up={id} onclick={(event) => move(id, -1, event.currentTarget.closest('ol') as HTMLElement)}><Icon name="chevron-up" size={12} /></button>
        <button type="button" class="oc-ibtn" aria-label={t('cplug.huddle.ask.move_down')} disabled={at === order.length - 1}
                data-ask-down={id} onclick={(event) => move(id, 1, event.currentTarget.closest('ol') as HTMLElement)}><Icon name="chevron-down" size={12} /></button>
      </span>
    </li>
  {/each}
</ol>
{#if question.recommend}
  <div class="hdq-why"><span class="hdq-rec">{t('cplug.huddle.ask.rec')}</span> {t(same ? 'cplug.huddle.ask.rank_same' : 'cplug.huddle.ask.rank_differs')}{#if question.recommend.reason}: <TaskManagerMarkdown text={question.recommend.reason} inline />{/if}</div>
{/if}
{#if value?.touched !== true}
  <div class="hdq-qfoot"><Button size="sm" data-ask-keep={question.id} onclick={() => onChange({ order: [...order], touched: true })}>{t('cplug.huddle.ask.keep_order')}</Button></div>
{/if}
