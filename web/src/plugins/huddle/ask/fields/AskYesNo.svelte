<script lang="ts">
  import { t } from '../../../sdk';
  import { Button } from '../../../sdk/ui';
  import type { AskQuestion, AskValue } from '../ask-model';
  import TaskManagerMarkdown from '../../TaskManagerMarkdown.svelte';
  import { mdPlain } from '../../task-manager-markdown';

  let { question, value, onChange }: { question: AskQuestion; value: AskValue | undefined; onChange: (patch: AskValue) => void } = $props();
  const labels = $derived([question.labels?.[0] ?? t('cplug.huddle.ask.yes'), question.labels?.[1] ?? t('cplug.huddle.ask.no')]);
  const rec = $derived(question.recommend);
</script>

<div class="hdq-pills" role="radiogroup" aria-label={mdPlain(question.prompt)} data-ask-field={question.id}>
  {#each [true, false] as answer, at (answer)}
    <Button role="radio" aria-checked={value?.value === answer} data-ask-pick={answer ? 'yes' : 'no'}
            onclick={() => onChange({ value: answer })}><TaskManagerMarkdown text={labels[at] ?? ''} inline /></Button>
  {/each}
</div>
{#if rec && typeof rec.value === 'boolean'}
  <div class="hdq-why"><span class="hdq-rec">{t('cplug.huddle.ask.rec')}</span> <TaskManagerMarkdown text={(rec.value ? labels[0] : labels[1]) ?? ''} inline />{#if rec.reason}: <TaskManagerMarkdown text={rec.reason} inline />{/if}</div>
{/if}
