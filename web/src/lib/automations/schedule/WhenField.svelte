<!-- a new automation -->
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Field from '../../base/Field.svelte';
  import Segmented from '../../base/Segmented.svelte';
  import * as api from '../api';
  import { refusalCode, refusalText } from '../format';
  import { pageClock } from '../page-store.svelte';
  import './schedule.css';
  import { checkCron } from './compose';
  import WhenPick from './WhenPick.svelte';
  import WhenWords from './WhenWords.svelte';
  import { cronToWords, fireText, type WordsOutcome } from './words-model';

  type Mode = 'words' | 'pick' | 'cron';
  let { cron = $bindable(), pending = $bindable(null), initialMode = 'words' }: { cron: string; pending: WordsOutcome | null; initialMode?: Mode } = $props();

  // svelte-ignore state_referenced_locally
  let mode = $state<Mode>(initialMode);
  let preview = $state<api.SchedulePreview | null>(null);
  let checking = $state(false);
  const MODES: Mode[] = ['words', 'pick', 'cron'];
  const MODE_OPTIONS = $derived(MODES.map((m) => ({ value: m, label: t(`automations.simple.when.mode_${m}`), attrs: { 'data-w-mode': m } })));
  const verdict = $derived(cron.trim() ? checkCron(cron) : null);
  const words = $derived(cronToWords(cron));

  $effect(() => {
    const text = cron.trim();
    preview = null;
    if (!text || (verdict && !verdict.ok)) {
      checking = false;
      return;
    }
    checking = true;
    const timer = setTimeout(async () => {
      try {
        const answer = await api.previewSchedule(text);
        if (text === cron.trim()) preview = answer;
      } catch (error) {
        if (text === cron.trim()) preview = { ok: false, reason: refusalCode(error) || refusalText(error) };
      } finally {
        if (text === cron.trim()) checking = false;
      }
    }, 350);
    return () => clearTimeout(timer);
  });
</script>

<div class="ap-pn-f w-when" data-when data-mode={mode}>
  <span class="oc-label" data-when-label>{t('automations.simple.when.label')}</span>
  <Segmented label={t('automations.simple.when.modes_aria')} options={MODE_OPTIONS} bind:value={() => mode, (next) => (mode = next as Mode)} />
  <div class="w-pane" data-pane="words" hidden={mode !== 'words'}>
    <WhenWords bind:cron bind:pending onPick={() => (mode = 'pick')} />
  </div>
  <div class="w-pane" data-pane="pick" hidden={mode !== 'pick'}>
    <WhenPick bind:cron />
  </div>
  <div class="w-pane" data-pane="cron" hidden={mode !== 'cron'}>
    <Field
      label={t('automations.simple.cron.label')}
      data-auto-field="cron"
      maxlength={120}
      autocomplete="off"
      spellcheck={false}
      aria-describedby="ap-ed-fires"
      placeholder={t('automations.simple.cron.placeholder')}
      bind:value={cron}
    />
    <p class="w-note">{t('automations.simple.cron.note_before')} <Button variant="quiet" size="sm" data-w-cron={t('automations.simple.cron.example')} title={t('automations.simple.cron.example_title')} onclick={() => (cron = t('automations.simple.cron.example'))}>{t('automations.simple.cron.example')}</Button> {t('automations.simple.cron.note_after')}</p>
  </div>
  <div id="ap-ed-fires" class="ap-pn-edfires w-now" data-cron-preview role="status" aria-live="polite">
    {#if verdict && !verdict.ok}
      <span class="ap-pn-bad" data-cron-refused>{verdict.text}</span>
    {:else if preview && !preview.ok}
      <span class="ap-pn-bad" data-cron-refused>{t(preview.reason === 'never_fires' ? 'automations.page.editor.never_fires' : 'automations.page.editor.bad_cron')}</span>
    {:else if preview && preview.ok && preview.fires.length === 0}
      <span class="ap-pn-bad" data-cron-refused>{t('automations.page.editor.never_fires')}</span>
    {:else if preview && preview.ok}
      <div class="w-now__top">
        <span class="pl-label">{t('automations.simple.now.current')}</span>
        <span class="w-now__w">{words ?? t('automations.simple.words.custom')}</span>
        <span class="w-now__c ap-num">{cron.trim()}</span>
      </div>
      <span class="pl-label">{preview.fires.length < 5 ? t('automations.simple.now.next_runs') : t('automations.simple.now.next_five')}</span>
      <ol>
        {#each preview.fires.slice(0, 5) as fire (fire.utc)}<li class="ap-num">{fireText(pageClock(), Date.parse(fire.utc) / 1000, preview.fires.slice(0, 5).map((f) => Date.parse(f.utc) / 1000))}</li>{/each}
      </ol>
    {:else if checking}
      <span class="ap-pn-dim">{t('automations.cron.checking')}</span>
    {/if}
  </div>
</div>
