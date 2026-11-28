<script lang="ts">
  import { t } from '../../../sdk';
  import { Button } from '../../../sdk/ui';
  import { baseField } from '../../task-manager-base-field';
  import { toggleChoice, type AskQuestion, type AskValue } from '../ask-model';
  import TaskManagerMarkdown from '../../TaskManagerMarkdown.svelte';
  import { mdPlain } from '../../task-manager-markdown';

  let { question, value, busy = false, onChange }: { question: AskQuestion; value: AskValue | undefined; busy?: boolean; onChange: (patch: AskValue) => void } = $props();
  const multi = $derived(question.type === 'multi');
  const pills = $derived(!multi && !!question.command);
  const options = $derived(question.options ?? []);
  const picked = (id: string): boolean => (multi ? (value?.choices ?? []).includes(id) : value?.choice === id);
  const stop = $derived(options.find((o) => picked(o.id))?.id ?? options[0]?.id);

  function pick(id: string): void {
    onChange(multi ? toggleChoice(question, value, id) : { choice: id, other: '' });
  }

  function onKeydown(event: KeyboardEvent): void {
    const step = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? -1 : 0;
    if (!step || event.altKey || event.metaKey || event.ctrlKey) return;
    const rows = [...(event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('[data-ask-option]')];
    const at = rows.indexOf(event.target as HTMLElement);
    if (at < 0) return;
    event.preventDefault();
    rows[(at + step + rows.length) % rows.length]?.focus();
  }

  function typeOther(text: string): void {
    onChange(multi ? { other: text } : { other: text, choice: text.trim() ? null : value?.choice });
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions, a11y_interactive_supports_focus -->
<div class:hdq-opts={!pills} class:hdq-pills={pills} role={multi ? 'group' : 'radiogroup'} aria-label={mdPlain(question.prompt)} data-ask-field={question.id} onkeydown={onKeydown}>
  {#each options as option, at (option.id)}
    {#if pills}
      
      <Button role="radio" aria-checked={picked(option.id)} tabindex={option.id === stop ? 0 : -1} disabled={busy} data-ask-option={option.id}
              onclick={() => pick(option.id)}><TaskManagerMarkdown text={option.label} inline />{#if option.recommended}<span class="hdq-rec">{t('cplug.huddle.ask.rec')}</span>{/if}</Button>
    {:else}
      <button type="button" role={multi ? 'checkbox' : 'radio'} aria-checked={picked(option.id)} tabindex={option.id === stop ? 0 : -1}
              class="hdq-opt" class:hdq-opt--radio={!multi} data-ask-option={option.id} onclick={() => pick(option.id)}>
        <span class="hdq-mark" aria-hidden="true"></span>
        <span>{at + 1}. <TaskManagerMarkdown text={option.label} inline />{#if option.recommended}<span class="hdq-rec">{t('cplug.huddle.ask.rec')}</span>{/if}</span>
        {#if option.recommended && option.reason}<span class="hdq-why"><TaskManagerMarkdown text={option.reason} inline /></span>{/if}
      </button>
    {/if}
  {/each}
  {#if busy && pills}<span class="hdq-sending" role="status" data-ask-sending={question.id}>{t('cplug.huddle.ask.sending')}</span>{/if}
  {#if question.other}
    <input class="hdq-input" use:baseField type="text" value={value?.other ?? ''} placeholder={t('cplug.huddle.ask.other_placeholder')}
           aria-label={t('cplug.huddle.ask.other')} maxlength="500" data-ask-other={question.id}
           oninput={(event) => typeOther(event.currentTarget.value)} />
  {/if}
</div>
