<script lang="ts">
  /* redraws the saved draft after a reload */
  import { untrack } from 'svelte';
  import type { AnswerBody, PublicPrompt } from './board-client';
  import { t } from './strings';

  interface Props { prompts: PublicPrompt[]; initial?: AnswerBody[]; onchange?: (answers: AnswerBody[]) => void }
  let { prompts, initial = [], onchange }: Props = $props();

  const MAX_TEXT = 4000;

  const seed = untrack(() => seeded(initial));
  let picks = $state<Record<string, string[]>>(seed.picks);
  let checks = $state<Record<string, boolean>>(seed.checks);
  let texts = $state<Record<string, string>>(seed.texts);

  function seeded(saved: AnswerBody[]): { picks: Record<string, string[]>; checks: Record<string, boolean>; texts: Record<string, string> } {
    const out = { picks: {} as Record<string, string[]>, checks: {} as Record<string, boolean>, texts: {} as Record<string, string> };
    for (const answer of saved) {
      if (answer.options) out.picks[answer.prompt] = [...answer.options];
      if (typeof answer.checked === 'boolean') out.checks[answer.prompt] = answer.checked;
      if (typeof answer.text === 'string') out.texts[answer.prompt] = answer.text;
    }
    return out;
  }

  function changed(): void {
    onchange?.(given());
  }

  function given(): AnswerBody[] {
    const out: AnswerBody[] = [];
    for (const prompt of prompts) {
      if ((prompt.kind === 'choice' || prompt.kind === 'multi') && (picks[prompt.id]?.length ?? 0) > 0) out.push({ prompt: prompt.id, options: picks[prompt.id] });
      else if (prompt.kind === 'check' && prompt.id in checks) out.push({ prompt: prompt.id, checked: checks[prompt.id] });
      else if (prompt.kind === 'question' && (texts[prompt.id] ?? '').trim()) out.push({ prompt: prompt.id, text: texts[prompt.id]!.trim() });
    }
    return out;
  }

  function pick(prompt: PublicPrompt, option: string, on: boolean): void {
    const now = picks[prompt.id] ?? [];
    picks[prompt.id] = prompt.kind === 'choice' ? [option] : on ? [...now.filter((o) => o !== option), option] : now.filter((o) => o !== option);
    changed();
  }
</script>

{#if prompts.length > 0}
  <section class="pb-section pbf" data-visitor-answers>
    <h2 class="pb-label">{t('cplug.reviewboard.public.page.prompts')}</h2>
    <p class="pb-hint">{t('cplug.reviewboard.public.page.prompts_answer')}</p>
    <ol class="pb-prompts">
      {#each prompts as prompt (prompt.id)}
        <li class="pbf-prompt">
          <span class="pb-prompt-label" id="pbf-q-{prompt.id}">{prompt.label}</span>
          {#if prompt.kind === 'choice' || prompt.kind === 'multi'}
            <div class="pbf-options" role="group" aria-labelledby="pbf-q-{prompt.id}">
              {#each prompt.options as option (option.id)}
                <label class="oc-pick">
                  {#if prompt.kind === 'choice'}
                    <input type="radio" class="oc-pick__input" name="pbf-{prompt.id}" checked={(picks[prompt.id] ?? []).includes(option.id)}
                           onchange={(e) => pick(prompt, option.id, e.currentTarget.checked)} />
                  {:else}
                    <input type="checkbox" class="oc-pick__input" name="pbf-{prompt.id}" checked={(picks[prompt.id] ?? []).includes(option.id)}
                           onchange={(e) => pick(prompt, option.id, e.currentTarget.checked)} />
                  {/if}
                  <span class="oc-pick__text"><span class="oc-pick__label">{option.label}</span></span>
                </label>
              {/each}
            </div>
          {:else if prompt.kind === 'check'}
            <div class="pbf-options" role="radiogroup" aria-labelledby="pbf-q-{prompt.id}">
              {#each [true, false] as value (value)}
                <label class="oc-pick">
                  <input type="radio" class="oc-pick__input" name="pbf-{prompt.id}" checked={checks[prompt.id] === value} onchange={() => { checks[prompt.id] = value; changed(); }} />
                  <span class="oc-pick__text"><span class="oc-pick__label">{t(value ? 'cplug.reviewboard.public.page.check_yes' : 'cplug.reviewboard.public.page.check_no')}</span></span>
                </label>
              {/each}
            </div>
          {:else}
            <textarea class="pbf-text" data-field rows="3" maxlength={MAX_TEXT} aria-labelledby="pbf-q-{prompt.id}"
                      value={texts[prompt.id] ?? ''} oninput={(e) => { texts[prompt.id] = e.currentTarget.value; changed(); }}></textarea>
          {/if}
        </li>
      {/each}
    </ol>
  </section>
{/if}
