<script lang="ts">
  import { t } from '../sdk';
  import { Button, Check, Field, IconButton } from '../sdk/ui';
  import type { AnswerRow, BoardPrompt } from './board-model';
  import { answerWords, type Ghost } from './tray-model';

  interface Props {
    prompt: BoardPrompt;
    answer: AnswerRow | null;
    ghost: Ghost | null;
    readonly?: boolean;
    highlighted?: boolean;
    onpick: (option: string) => void;
    oncheck: (checked: boolean) => void;
    ontext: (text: string) => void;
    onnote: (text: string) => void;
    oncopy: () => void;
  }

  let { prompt, answer, ghost, readonly = false, highlighted = false, onpick, oncheck, ontext, onnote, oncopy }: Props = $props();

  let noteOpen = $state(false);
  const yes = $derived(t('cplug.reviewboard.tray.yes'));
  const no = $derived(t('cplug.reviewboard.tray.no'));
  const ghostWords = $derived(ghost ? answerWords(prompt, ghost.answer, yes, no) : '');
  const picked = $derived(new Set(answer?.options ?? []));
</script>

<div class="rb-prompt" data-prompt={prompt.id} data-answered={!!answer} data-highlighted={highlighted}>
  {#if prompt.kind !== 'check'}<p class="rb-prompt-label">{prompt.label}</p>{/if}

  {#if prompt.kind === 'choice' || prompt.kind === 'multi'}
    <div class="rb-pills" role={prompt.kind === 'choice' ? 'radiogroup' : 'group'} aria-label={prompt.label}>
      {#each prompt.options ?? [] as option (option.id)}
        <Button size="sm" role={prompt.kind === 'choice' ? 'radio' : 'checkbox'} aria-checked={picked.has(option.id)}
                data-option={option.id} disabled={readonly} onclick={() => onpick(option.id)}>{option.label}</Button>
      {/each}
    </div>
  {:else if prompt.kind === 'check'}
    <Check label={prompt.label} checked={answer?.checked === true} disabled={readonly} data-prompt-check={prompt.id}
           onToggle={(next) => oncheck(next)} />
  {:else}
    <Field multiline block rows={1} aria-label={prompt.label} placeholder={t('cplug.reviewboard.tray.question_placeholder')}
           value={answer?.text ?? ''} disabled={readonly} data-prompt-text={prompt.id}
           oninput={(e) => ontext((e.currentTarget as HTMLInputElement).value)} />
  {/if}

  {#if ghost && !readonly}
    <p class="rb-ghost" data-ghost={prompt.id}>
      <span>{t('cplug.reviewboard.tray.ghost', { revision: ghost.revision, answer: ghostWords || t('cplug.reviewboard.tray.no_answer') })}</span>
      <IconButton label={t('cplug.reviewboard.tray.same')} icon="copy" variant="quiet" iconSize={14} data-ghost-copy={prompt.id} onclick={oncopy} />
    </p>
  {/if}

  {#if answer && !readonly}
    <div class="rb-prompt-note">
      <IconButton label={t('cplug.reviewboard.tray.note_on')} icon="pencil" variant="quiet" iconSize={14}
                  pressed={noteOpen || !!answer.note} data-prompt-note-toggle={prompt.id} onclick={() => (noteOpen = !noteOpen)} />
      {#if noteOpen || answer.note}
        <Field multiline block rows={1} aria-label={t('cplug.reviewboard.tray.note_on')} value={answer.note}
               oninput={(e) => onnote((e.currentTarget as HTMLInputElement).value)} />
      {/if}
    </div>
  {:else if answer?.note}
    <p class="rb-note-text">{answer.note}</p>
  {/if}
</div>
