<script lang="ts">
  import { t } from '../../../sdk';
  import { Button } from '../../../sdk/ui';
  import { baseField } from '../../task-manager-base-field';
  import type { AskQuestion, AskValue } from '../ask-model';
  import TaskManagerMarkdown from '../../TaskManagerMarkdown.svelte';
  import { mdPlain } from '../../task-manager-markdown';

  let { question, value, onChange }: { question: AskQuestion; value: AskValue | undefined; onChange: (patch: AskValue) => void } = $props();
  const suggestion = $derived(question.recommend?.text ?? '');
  const text = $derived(value?.text ?? '');
</script>

{#if question.type === 'short_text'}
  <input class="hdq-input" use:baseField type="text" value={text} placeholder={question.placeholder ?? ''} maxlength={question.max_length}
         aria-label={mdPlain(question.prompt)} data-ask-field={question.id} oninput={(event) => onChange({ text: event.currentTarget.value })} />
{:else}
  <textarea class="hdq-input" use:baseField rows="3" value={text} placeholder={question.placeholder ?? suggestion} maxlength={question.max_length}
            aria-label={mdPlain(question.prompt)} data-ask-field={question.id} oninput={(event) => onChange({ text: event.currentTarget.value })}></textarea>
{/if}
{#if suggestion && text !== suggestion}
  <div class="hdq-why"><span class="hdq-rec">{t('cplug.huddle.ask.rec')}</span> <TaskManagerMarkdown text={question.recommend?.reason ?? ''} inline />
    <Button size="sm" data-ask-suggest={question.id} onclick={() => onChange({ text: suggestion })}>{t('cplug.huddle.ask.use_suggestion')}</Button></div>
{/if}
