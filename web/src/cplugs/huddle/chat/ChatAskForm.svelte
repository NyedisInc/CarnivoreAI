<script lang="ts">
  import { onDestroy } from 'svelte';
  import { t } from '../../sdk';
  import { Button, Icon } from '../../sdk/ui';
  import { baseField } from '../task-manager-base-field';
  import type { HuddleItem, TaskManagerMessage } from '../huddle-model';
  import { fetchFileBlob, uploadFile } from '../task-manager-files-api';
  import TaskManagerMarkdown from '../TaskManagerMarkdown.svelte';
  import { createAsk } from '../ask/ask-state.svelte';
  import { takeRecommendation, toggleChoice, type AskQuestion, type AskValue } from '../ask/ask-model';
  import AskRank from '../ask/fields/AskRank.svelte';
  import AskText from '../ask/fields/AskText.svelte';
  import '../ask/ask-form.css';
  import { ownAnswer } from './chat-ask-rows';

  let { item, message }: { item: HuddleItem; message: TaskManagerMessage } = $props();

  // svelte-ignore state_referenced_locally
  const ask = createAsk(message.id);
  void ask.load();

  let open = $state<string | null>(null);
  let uploading = $state<string | null>(null);
  let picker = $state<HTMLInputElement | null>(null);
  let pickFor = $state<string | null>(null);
  let thumbs = $state<Record<string, string>>({});

  const questions = $derived(ask.questions.length ? ask.questions : (message.form ?? []));
  const yesNo = $derived([t('cplug.huddle.ask.yes'), t('cplug.huddle.ask.no')] as [string, string]);
  const files = $derived(questions.filter((q) => (ask.values[q.id]?.files?.length ?? 0) > 0).length);
  const done = $derived(ask.progress.done);
  const left = $derived(questions.length - done);
  const tally = $derived(files
    ? t('cplug.huddle.chat.ask.form.tally_files', { done, total: questions.length, open: left, files })
    : t('cplug.huddle.chat.ask.form.tally', { done, total: questions.length, open: left }));

  function recommended(question: AskQuestion, id: string): boolean {
    const rec = takeRecommendation(question);
    if (!rec) return false;
    if (question.type === 'yes_no') return String(rec.value) === id;
    return question.type === 'multi' ? (rec.choices ?? []).includes(id) : rec.choice === id;
  }

  function pick(question: AskQuestion, id: string): void {
    ask.set(question.id, question.type === 'multi' ? toggleChoice(question, ask.values[question.id], id) : { choice: id, other: '' });
  }

  function attach(id: string): void {
    pickFor = id;
    picker?.click();
  }

  async function picked(event: Event & { currentTarget: HTMLInputElement }): Promise<void> {
    const file = event.currentTarget.files?.[0];
    const id = pickFor;
    event.currentTarget.value = '';
    if (!file || !id) return;
    uploading = id;
    try {
      const saved = await uploadFile(item.id, file);
      ask.set(id, { files: [...(ask.values[id]?.files ?? []), { id: saved.id, name: saved.name }] });
      if (file.type.startsWith('image/')) {
        const blob = await fetchFileBlob(item.id, saved.id);
        thumbs = { ...thumbs, [saved.id]: URL.createObjectURL(blob) };
      }
    } catch (error) {
      console.warn('huddle: could not attach the file', error);
    } finally {
      uploading = null;
    }
  }

  function unattach(id: string, fileId: string): void {
    ask.set(id, { files: (ask.values[id]?.files ?? []).filter((f) => f.id !== fileId) });
  }

  onDestroy(() => Object.values(thumbs).forEach((url) => URL.revokeObjectURL(url)));
</script>

<section class="hca" data-chat-ask-form={message.id}>
  <div class="hca-strip">
    <span class="hdq-label">{t('cplug.huddle.chat.ask.form.label')}</span>
    <span class="hca-hint">{t('cplug.huddle.chat.ask.form.hint')}</span>
  </div>
  {#each questions as question, at (question.id)}
    {@const value = ask.values[question.id]}
    {@const chip = ownAnswer(question, value, yesNo)}
    {@const isOpen = open === question.id}
    <div class="hca-q" data-open={isOpen} data-chat-ask-q={question.id}>
      <button type="button" class="hca-row" data-base-exempt="a disclosure row: the whole question row is the hit area (mockup C)" aria-expanded={isOpen} onclick={() => (open = isOpen ? null : question.id)}>
        <span class="hca-n">{at + 1}.</span>
        <span class="hca-t"><TaskManagerMarkdown text={question.prompt} inline /></span>
        <span class="hca-chip-slot">{#if chip}<span class="hca-chip" data-chat-ask-chip>{chip}</span>{/if}</span>
        <span class="hca-clip" title={value?.files?.length ? t('cplug.huddle.chat.ask.form.has_file') : undefined}>
          {#if value?.files?.length}<span data-chat-ask-clip><Icon name="paperclip" size={13} /></span>{/if}
        </span>
        <span class="hca-v"><Icon name="chevron-down" size={12} /></span>
      </button>
      {#if isOpen}
        <div class="hca-body">
          {#if question.help}<div class="hdq-why"><TaskManagerMarkdown text={question.help} /></div>{/if}
          {#if question.type === 'single' || question.type === 'multi'}
            <div class="hdq-opts" role={question.type === 'multi' ? 'group' : 'radiogroup'}>
              {#each question.options ?? [] as option, n (option.id)}
                {@const on = question.type === 'multi' ? (value?.choices ?? []).includes(option.id) : value?.choice === option.id}
                <button type="button" role={question.type === 'multi' ? 'checkbox' : 'radio'} aria-checked={on} class="hdq-opt hca-opt" data-base-exempt="the ask form's option row (hdq-opt, AskChoice)"
                        class:hdq-opt--radio={question.type !== 'multi'} data-ask-option={option.id} onclick={() => pick(question, option.id)}>
                  <span class="hdq-mark" aria-hidden="true"></span>
                  <span class="hca-star">{#if option.recommended}<span title={t('cplug.huddle.chat.ask.form.recommended')} data-chat-ask-star><Icon name="star" size={11} fill="solid" /></span>{/if}</span>
                  <span>{n + 1}. <TaskManagerMarkdown text={option.label} inline /></span>
                  {#if option.recommended && option.reason}<span class="hdq-why hca-why">{t('cplug.huddle.chat.ask.form.why', { reason: option.reason })}</span>{/if}
                </button>
              {/each}
            </div>
          {:else if question.type === 'yes_no'}
            <div class="hdq-pills" role="radiogroup">
              {#each [true, false] as answer, n (answer)}
                <Button role="radio" aria-checked={value?.value === answer} data-ask-pick={answer ? 'yes' : 'no'} onclick={() => ask.set(question.id, { value: answer })}>
                  {#if recommended(question, String(answer))}<span class="hca-star" data-chat-ask-star><Icon name="star" size={11} fill="solid" /></span>{/if}
                  <TaskManagerMarkdown text={(question.labels ?? yesNo)[n] ?? ''} inline />
                </Button>
              {/each}
            </div>
            {#if question.recommend?.reason}<div class="hdq-why">{t('cplug.huddle.chat.ask.form.why', { reason: question.recommend.reason })}</div>{/if}
          {:else if question.type === 'rank'}
            <AskRank {question} {value} onChange={(patch: AskValue) => ask.set(question.id, patch)} />
          {:else}
            <AskText {question} {value} onChange={(patch: AskValue) => ask.set(question.id, patch)} />
            {#if question.recommend?.text}
              <div class="hdq-why hca-rectext">
                <span class="hca-star" data-chat-ask-star><Icon name="star" size={11} fill="solid" /></span>
                <TaskManagerMarkdown text={question.recommend.text} inline />
                <Button size="sm" onclick={() => ask.take(question.id)}>{t('cplug.huddle.chat.ask.form.use_it')}</Button>
              </div>
            {/if}
          {/if}
          <div class="hca-x">
            <input class="hdq-input" use:baseField data-field type="text" maxlength="500" value={value?.note ?? ''} placeholder={t('cplug.huddle.ask.note_placeholder')}
                   aria-label={t('cplug.huddle.ask.note')} oninput={(event) => ask.set(question.id, { note: event.currentTarget.value })} />
            <Button size="icon" aria-label={t('cplug.huddle.chat.ask.form.attach', { n: at + 1 })} aria-pressed={!!value?.files?.length}
                    disabled={uploading !== null} data-chat-ask-attach={question.id} onclick={() => attach(question.id)}><Icon name="paperclip" size={14} /></Button>
            {#if uploading === question.id}<span class="hdq-why">{t('cplug.huddle.chat.ask.form.uploading')}</span>{/if}
          </div>
          {#each value?.files ?? [] as file (file.id)}
            <div class="hca-att" data-chat-ask-file={file.id}>
              {#if thumbs[file.id]}<img src={thumbs[file.id]} alt={file.name} />{/if}
              <span class="hca-att-name">{file.name}</span>
              <Button size="sm" onclick={() => unattach(question.id, file.id)}>{t('cplug.huddle.chat.ask.form.remove')}</Button>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/each}
  <div class="hca-bar">
    <span class="hdq-label">{t('cplug.huddle.chat.ask.form.answers')}</span>
    <span class="hca-tally" data-chat-ask-tally>{tally}</span>
    <Button size="sm" disabled={ask.canTakeAll === 0} title={t('cplug.huddle.chat.ask.form.accept_rec_tip')} data-chat-ask-accept
            onclick={() => ask.takeAll()}>{t('cplug.huddle.chat.ask.form.accept_rec')}</Button>
    <Button size="sm" variant="confirm" disabled={ask.submitting || ask.progress.requiredLeft > 0 || !ask.read} data-chat-ask-send
            onclick={() => void ask.submit()}>{ask.submitting ? t('cplug.huddle.chat.ask.form.sending') : t('cplug.huddle.chat.ask.form.send')}</Button>
  </div>
  {#if ask.error}<p class="hdq-note hdq-note--error" role="alert">{ask.error}</p>{/if}
  <input bind:this={picker} type="file" hidden onchange={picked} />
</section>

<style>
  @layer components {
    .hca {
      display: flex;
      flex-direction: column;
      min-width: 0;
      background: var(--oc-ground-raised);
      border: var(--oc-border) solid var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-primary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-body);
    }
    .hca-strip {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-height: var(--oc-titlerow-h, 2.25rem);
      padding: 0 var(--oc-space-3);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 calc(-1 * var(--oc-border)) 0 0 var(--oc-line-rule);
    }
    .hca-hint { margin-left: auto; color: var(--oc-text-secondary); white-space: nowrap; }
    .hca-q { box-shadow: inset 0 calc(-1 * var(--oc-border)) 0 0 var(--oc-line-panel); }
    .hca-q[data-open='true'] {
      background: var(--oc-ground-page);
      box-shadow: inset 2px 0 0 var(--oc-cyan), inset 0 calc(-1 * var(--oc-border)) 0 0 var(--oc-line-panel);
    }
    .hca-row {
      --_bd: transparent;
      display: grid;
      grid-template-columns: var(--oc-space-5) minmax(0, 1fr) auto 14px 12px;
      gap: var(--oc-space-2);
      align-items: center;
      width: 100%;
      min-height: calc(var(--oc-space-6) + var(--oc-space-1));
      padding: 0 var(--oc-space-3);
      border: var(--oc-border) solid transparent;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
    }
    .hca-row:hover { background: var(--oc-ground-hover); }
    .hca-n { color: var(--oc-yellow-bright); font-variant-numeric: tabular-nums; }
    .hca-t { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .hca-chip-slot { display: flex; justify-content: flex-end; min-width: 0; max-width: 18em; }
    .hca-chip {
      display: inline-block;
      max-width: 14em;
      padding: 0 var(--oc-space-1-5);
      overflow: hidden;
      border: var(--oc-border) solid var(--oc-cyan);
      border-radius: var(--oc-radius-sm);
      background: color-mix(in srgb, var(--oc-cyan) 9%, var(--oc-ground-field));
      color: var(--oc-text-bright);
      text-overflow: ellipsis;
      white-space: nowrap;
      vertical-align: middle;
    }
    .hca-clip { display: inline-flex; color: var(--oc-cyan); }
    .hca-v { display: inline-flex; color: var(--oc-text-dim); transition: transform var(--oc-motion, 160ms); }
    .hca-q[data-open='true'] .hca-v { transform: rotate(180deg); }
    .hca-body {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      padding: 0 var(--oc-space-3) var(--oc-space-3) calc(var(--oc-space-5) + var(--oc-space-3) + var(--oc-space-2));
    }
    .hca-opt { grid-template-columns: 1rem 0.9rem minmax(0, 1fr); }
    .hca-opt .hca-why { grid-column: 3; }
    .hca-star { display: inline-flex; align-self: center; color: var(--oc-yellow-bright); }
    .hca-rectext { display: flex; align-items: center; gap: var(--oc-space-1-5); }
    .hca-x { display: flex; align-items: center; gap: var(--oc-space-1-5); }
    .hca-att { display: flex; align-items: center; gap: var(--oc-space-2); color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); }
    .hca-att img { display: block; max-width: 132px; max-height: 88px; border: var(--oc-border) solid var(--oc-line-frame); border-radius: var(--oc-radius-sm); }
    .hca-att-name { min-width: 0; overflow-wrap: anywhere; }
    .hca-bar {
      position: sticky;
      bottom: 0;
      z-index: 1;
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      padding: var(--oc-space-2) var(--oc-space-3);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 var(--oc-border) 0 0 var(--oc-line-frame);
    }
    .hca-tally { flex: 1 1 auto; min-width: 0; color: var(--oc-text-secondary); }
  }
</style>
