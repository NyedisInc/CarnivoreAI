
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import Field from '../../base/Field.svelte';
  import * as api from '../api';
  import { refusalText } from '../format';
  import { data, pageClock } from '../page-store.svelte';
  import { browserZone, cronToWords, fireText, parseOutcome, type WordsOutcome } from './words-model';

  let { cron = $bindable(), pending = $bindable(null), onPick }: { cron: string; pending: WordsOutcome | null; onPick: () => void } = $props();

  const TRIES = [1, 2, 3, 4] as const;
  let text = $state('');
  let phase = $state<'idle' | 'reading' | 'result' | 'used' | 'empty'>('idle');
  let outcome = $state<WordsOutcome | null>(null);
  let written = cron;
  let token = 0;

  $effect(() => {
    const now = cron;
    if (now === written) return;
    written = now;
    text = cronToWords(now) ?? '';
    if (phase === 'result' || phase === 'used') clear('idle');
  });

  function clear(to: 'idle' | 'empty'): void {
    token += 1;
    outcome = null;
    pending = null;
    phase = to;
  }

  async function read(sentence?: string): Promise<void> {
    if (sentence !== undefined) text = sentence;
    const said = text.trim();
    if (!said) {
      clear('empty');
      return;
    }
    const mine = ++token;
    pending = null;
    outcome = null;
    phase = 'reading';
    let answer: WordsOutcome;
    try {
      answer = parseOutcome(await api.parseSchedule(said, browserZone()));
    } catch (error) {
      answer = { kind: 'refused', reason: 'ai_error', text: refusalText(error) };
    }
    if (mine !== token) return;
    outcome = answer;
    phase = 'result';
    pending = answer.kind === 'ok' ? answer : null;
  }

  function use(): void {
    if (!outcome || outcome.kind !== 'ok') return;
    written = outcome.cron;
    cron = outcome.cron;
    pending = null;
    phase = 'used';
  }

  function startOver(): void {
    text = '';
    clear('idle');
  }

  function key(e: KeyboardEvent): void {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    e.stopPropagation();
    void read();
  }

  function fireAt(stamp: string, list: { local: string }[]): string {
    return fireText(pageClock(), Date.parse(stamp) / 1000, list.map((f) => Date.parse(f.local) / 1000));
  }

  function inZoneText(stamp: string, zone: string): string {
    return new Date(stamp).toLocaleString('en-US', { timeZone: zone, weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).toLowerCase();
  }
</script>

<div class="w-q">
  <Field
    data-words-input
    id="w-text"
    bind:value={text}
    placeholder={t('automations.simple.words.placeholder')}
    autocomplete="off"
    spellcheck={false}
    aria-label={t('automations.simple.words.aria')}
    onkeydown={key}
  />
  <Button size="sm" data-w-read onclick={() => void read()}>{t('automations.simple.words.read')}</Button>
</div>
<div class="w-tries">
  <span class="oc-label">{t('automations.simple.words.try')}</span>
  {#each TRIES as n (n)}
    {@const said = t(`automations.simple.words.try_${n}`)}
    <Button size="sm" data-w-try={said} onclick={() => void read(said)}>{said}</Button>
  {/each}
</div>
<div class="w-res" data-words-result aria-live="polite">
  {#if phase === 'reading'}
    <p class="w-note" data-reading>{t('automations.simple.words.reading')}</p>
  {:else if phase === 'empty'}
    <p class="w-note">{t('automations.simple.words.empty')}</p>
  {:else if outcome && outcome.kind === 'refused'}
    <p class="ap-pn-bad" role="alert" data-words-refused={outcome.reason}>{outcome.text}</p>
    {#if outcome.reason === 'no_ai_connection'}
      <Button size="sm" data-w-to-pick onclick={onPick}>{t('automations.simple.when.mode_pick')}</Button>
    {/if}
    <p class="w-note">{t('automations.simple.words.unchanged')}</p>
  {:else if outcome && outcome.kind === 'ok'}
    {@const used = phase === 'used'}
    {@const ok = outcome}
    <Card title={used ? t('automations.simple.words.using') : t('automations.simple.words.reads_as')} compact data-used={used} data-words-card>
      {#snippet children()}
        <div class="w-card__w">{ok.words || t('automations.simple.words.custom')}</div>
        <div class="w-card__c ap-num">{ok.cron}</div>
        <div class="w-card__f">
          <span class="oc-label">{t('automations.simple.words.next_three')}</span>
          <ol>
            {#each ok.fires.slice(0, 3) as fire (fire.inZone)}
              <li class="ap-num">
                {#if ok.differs}
                  {t('automations.simple.words.zone_in', { zone: browserZone() })} {inZoneText(fire.inZone, browserZone())}, {t('automations.simple.words.zone_local', { zone: data.tz })} {fireAt(fire.local, ok.fires.slice(0, 3))}
                {:else}
                  {fireAt(fire.local, ok.fires.slice(0, 3))}
                {/if}
              </li>
            {/each}
          </ol>
          {#if ok.differs}<p class="w-note" data-zone-differs>{t('automations.simple.words.zone_differs', { zone: browserZone(), local: data.tz })}</p>{/if}
        </div>
        {#if !used}<p class="w-note">{t('automations.simple.words.check_note')}</p>{/if}
      {/snippet}
      {#snippet foot()}
        {#if used}
          <span class="w-ok">{t('automations.simple.words.done')}</span>
        {:else}
          <Button variant="confirm" size="sm" data-w-use onclick={use}>{t('automations.simple.words.use')}</Button>
          <Button size="sm" data-w-reset onclick={startOver}>{t('automations.simple.words.start_over')}</Button>
        {/if}
      {/snippet}
    </Card>
  {:else}
    <p class="w-note">{t('automations.simple.words.note')}</p>
  {/if}
</div>
