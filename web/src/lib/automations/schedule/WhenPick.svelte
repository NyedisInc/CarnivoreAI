
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import Select from '../../base/Select.svelte';
  import { buildCron, changeRepeat, defaultPick, HOUR_STEPS, MINUTE_STEPS, parsePick, REPEATS, type PickState, type Repeat } from './compose';
  import { dayName, dayOrdinal, monthName, nthWord } from './words-model';

  let { cron = $bindable() }: { cron: string } = $props();

  // svelte-ignore state_referenced_locally
  let pick = $state<PickState | null>(parsePick(cron));
  // svelte-ignore state_referenced_locally
  let viewMonth = $state((pick?.month ?? 1) - 1);
  // svelte-ignore state_referenced_locally
  let written = cron;

  $effect(() => {
    const now = cron;
    if (now === written) return;
    written = now;
    pick = parsePick(now);
    if (pick) viewMonth = pick.month - 1;
  });

  const year = new Date().getFullYear();
  const minutes = $derived.by(() => {
    const out: number[] = [];
    for (let m = 0; m < 60; m += 5) out.push(m);
    if (pick && !out.includes(pick.min)) out.push(pick.min);
    return out.sort((a, b) => a - b);
  });

  function commit(next: PickState): void {
    pick = next;
    written = buildCron(next);
    cron = written;
  }

  function repeat(rep: Repeat): void {
    if (!pick) return;
    const d = new Date();
    const next = changeRepeat(pick, rep, { month: d.getMonth() + 1, day: d.getDate() });
    if (rep === 'yeardate') viewMonth = next.month - 1;
    commit(next);
  }

  function set<K extends 'step' | 'min' | 'hour12' | 'nth' | 'wd'>(key: K, value: string): void {
    if (pick) commit({ ...pick, [key]: Number(value) });
  }

  function toggleDay(day: number): void {
    if (!pick) return;
    const has = pick.days.includes(day);
    if (has && pick.days.length === 1) return;
    commit({ ...pick, days: has ? pick.days.filter((d) => d !== day) : [...pick.days, day] });
  }

  function setDate(day: number): void {
    if (!pick) return;
    commit({ ...pick, dom: day, month: pick.rep === 'yeardate' ? viewMonth + 1 : pick.month });
  }

  function startPick(): void {
    commit(defaultPick());
    viewMonth = 0;
  }

  const firstWeekday = $derived(new Date(year, viewMonth, 1).getDay());
  const daysInView = $derived(new Date(year, viewMonth + 1, 0).getDate());
</script>

{#snippet sel(key: string, label: string, options: [number | string, string][], current: number | string, onchange: (v: string) => void)}
  <Select size="sm" data-w={key} aria-label={label} value={String(current)} options={options.map(([v, text]) => ({ value: String(v), label: text }))} onchange={(e) => onchange(e.currentTarget.value)} />
{/snippet}

{#if pick}
  {@const p = pick}
  <label class="w-row"><span class="w-lab">{t('automations.simple.pick.repeats')}</span>
    {@render sel('rep', t('automations.simple.pick.repeats_aria'), REPEATS.map((r) => [r, t(`automations.simple.pick.rep.${r}`)]), p.rep, (v) => repeat(v as Repeat))}
  </label>
  {#if p.rep === 'days'}
    <div class="w-row"><span class="w-lab">{t('automations.simple.pick.on')}</span>
      <div class="w-days" role="group" aria-label={t('automations.simple.pick.days_aria')}>
        {#each [0, 1, 2, 3, 4, 5, 6] as d (d)}
          <Button size="sm" data-w-day={d} aria-pressed={p.days.includes(d)} aria-label={dayName(d)} onclick={() => toggleDay(d)}>{t(`automations.simple.day_letter.${d}`)}</Button>
        {/each}
      </div>
    </div>
  {/if}
  {#if p.rep === 'nth'}
    <div class="w-row"><span class="w-lab">{t('automations.simple.pick.on_the')}</span>
      <div class="w-inl">
        {@render sel('nth', t('automations.simple.pick.nth_aria'), [1, 2, 3, 4].map((n) => [n, nthWord(n)]), p.nth, (v) => set('nth', v))}
        {@render sel('wd', t('automations.simple.pick.wd_aria'), [0, 1, 2, 3, 4, 5, 6].map((d) => [d, dayName(d)]), p.wd, (v) => set('wd', v))}
        <span class="w-q2">{t('automations.simple.pick.of_every_month')}</span>
      </div>
    </div>
  {/if}
  {#if p.rep === 'monthdate'}
    <div class="w-row"><span class="w-lab">{t('automations.simple.pick.on_the')}</span>
      <div>
        <div class="w-cal w-cal--days">
          <Card title={t('automations.simple.pick.dom_aria')} compact role="group">
            <div class="w-cal__g">
              {#each Array.from({ length: 31 }, (_, i) => i + 1) as d (d)}
                <Button variant="quiet" size="sm" data-w-date={d} aria-pressed={p.dom === d} aria-label={t('automations.simple.pick.the_ordinal', { ordinal: dayOrdinal(d) })} onclick={() => setDate(d)}>{d}</Button>
              {/each}
            </div>
          </Card>
        </div>
        <p class="w-note">{p.dom > 28 ? t('automations.simple.pick.note_skip', { ordinal: dayOrdinal(p.dom) }) : t('automations.simple.pick.note_monthly', { ordinal: dayOrdinal(p.dom) })}</p>
      </div>
    </div>
  {/if}
  {#if p.rep === 'yeardate'}
    <div class="w-row"><span class="w-lab">{t('automations.simple.pick.on')}</span>
      <div>
        <div class="w-cal">
        <Card title={`${monthName(viewMonth + 1)} ${year}`} compact role="group">
          {#snippet actions()}
            <Button size="sm" data-w-cal="-1" aria-label={t('automations.simple.pick.cal_prev')} disabled={viewMonth === 0} onclick={() => (viewMonth = Math.max(0, viewMonth - 1))}>&#8249;</Button>
            <Button size="sm" data-w-cal="1" aria-label={t('automations.simple.pick.cal_next')} disabled={viewMonth === 11} onclick={() => (viewMonth = Math.min(11, viewMonth + 1))}>&#8250;</Button>
          {/snippet}
          {#snippet children()}
            <div class="w-cal__w" aria-hidden="true">
              {#each [0, 1, 2, 3, 4, 5, 6] as d (d)}<span>{t(`automations.simple.day_letter.${d}`)}</span>{/each}
            </div>
            <div class="w-cal__g">
              {#each Array.from({ length: firstWeekday }, (_, i) => i) as i (i)}<span class="w-cal__b"></span>{/each}
              {#each Array.from({ length: daysInView }, (_, i) => i + 1) as d (d)}
                <Button variant="quiet" size="sm" data-w-date={d} aria-pressed={p.month - 1 === viewMonth && p.dom === d} aria-label={t('automations.simple.pick.date_label', { day: d, month: monthName(viewMonth + 1) })} onclick={() => setDate(d)}>{d}</Button>
              {/each}
            </div>
          {/snippet}
        </Card>
        </div>
        <p class="w-note">{t('automations.simple.pick.note_yearly', { month: monthName(p.month), day: p.dom })}</p>
      </div>
    </div>
  {/if}
  {#if p.rep === 'hours'}
    <div class="w-row"><span class="w-lab">{t('automations.simple.pick.every')}</span>
      <div class="w-inl">
        {@render sel('step', t('automations.simple.pick.step_hours_aria'), HOUR_STEPS.map((n) => [n, n === 1 ? t('automations.simple.pick.hour_one') : t('automations.simple.pick.hours_many', { n })]), p.step, (v) => set('step', v))}
        <span class="w-q2">{t('automations.simple.pick.at')}</span>
        {@render sel('min', t('automations.simple.pick.min_past_aria'), minutes.map((m) => [m, t('automations.simple.pick.past', { min: m })]), p.min, (v) => set('min', v))}
      </div>
    </div>
  {:else if p.rep === 'minutes'}
    <div class="w-row"><span class="w-lab">{t('automations.simple.pick.every')}</span>
      <div class="w-inl">
        {@render sel('step', t('automations.simple.pick.step_minutes_aria'), MINUTE_STEPS.map((n) => [n, t('automations.simple.pick.minutes_many', { n })]), p.step, (v) => set('step', v))}
      </div>
    </div>
  {:else}
    <div class="w-row"><span class="w-lab">{t('automations.simple.pick.at')}</span>
      <div class="w-inl">
        {@render sel('hour12', t('automations.simple.pick.hour_aria'), Array.from({ length: 12 }, (_, i) => [i + 1, String(i + 1)]), p.hour12, (v) => set('hour12', v))}
        {@render sel('min', t('automations.simple.pick.minute_aria'), minutes.map((m) => [m, `:${String(m).padStart(2, '0')}`]), p.min, (v) => set('min', v))}
        {@render sel('ap', t('automations.simple.pick.ap_aria'), [['am', 'am'], ['pm', 'pm']], p.ap, (v) => commit({ ...p, ap: v === 'pm' ? 'pm' : 'am' }))}
      </div>
    </div>
  {/if}
{:else}
  <p class="w-note" data-no-pick>{t('automations.simple.pick.no_pick')}</p>
  <div class="w-row"><Button size="sm" data-w-startpick onclick={startPick}>{t('automations.simple.pick.start_pick')}</Button></div>
{/if}
