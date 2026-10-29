
<script lang="ts">
  import { untrack } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import List from '../../base/List.svelte';
  import ListRow from '../../base/ListRow.svelte';
  import State from '../../base/State.svelte';
  import Switch from '../../base/Switch.svelte';
  import Tag from '../../base/Tag.svelte';
  import type { Automation } from '../api';
  import { cronWords } from '../cron-words';
  import { runNow } from '../list-state.svelte';
  import { isUnread } from '../logic/feed';
  import { lightOf } from '../logic/marks';
  import Mark from '../Mark.svelte';
  import { cardWord, tagToneOf } from '../overview/overview-model';
  import { metaLine } from '../overview/card-meta';
  import { overview, setEnabled } from '../overview/overview-state.svelte';
  import { closeDrawer, data, openEdit, openInAdvanced, pageClock, setTop } from '../page-store.svelte';
  import { unread } from '../read-state.svelte';
  import { fireText } from '../schedule/words-model';
  import { statusSentence } from './drawer-model';
  import { dr, loadAutomation } from './drawer-state.svelte';
  import LastRun from './LastRun.svelte';

  let { automation }: { automation: Automation } = $props();

  const id = $derived(automation.automation_id);
  const enabled = $derived(overview.pending[id] ?? automation.enabled);
  const clock = $derived(pageClock());
  const mine = $derived(dr.key === `automation:${id}`);
  const last = $derived(mine ? (dr.runs[0] ?? null) : null);
  const light = $derived(lightOf(enabled, data.paused, automation.recent?.[0]?.status ?? null));
  const word = $derived(cardWord(automation, enabled, data.paused));
  const next = $derived(automation.next_fire_at ? `${clock.rel(automation.next_fire_at, data.now)}, ${clock.short(automation.next_fire_at, data.now)}` : '-');
  const sentence = $derived(
    statusSentence({
      enabled,
      paused: data.paused,
      last,
      reviewed: last ? !isUnread(last, { seenAt: unread.seenAt, read: new Set(unread.read) }, data.now) : true,
      nextText: next,
    }),
  );
  const asks = $derived(String(automation.target.prompt ?? automation.target.command ?? '').trim());

  $effect(() => {
    const a = automation;
    void `${a.automation_id}|${a.trigger.cron}|${a.enabled}|${a.run_count}|${a.next_fire_at}`;
    if (data.fixture) return;
    untrack(() => void loadAutomation(a.automation_id, a.trigger.cron, a.next_fire_at, a.enabled));
  });

  function edit(): void {
    closeDrawer();
    if (data.top === 'sessions') setTop('automations');
    openEdit(id);
  }
</script>

<Card title={t('automations.simple.dr.label_automation')} compact>
  {#snippet children()}
    <div class="ap-dr-st">
      {#if light.kind === 'run'}<Mark status={light.status} size={14} />{:else}<Mark light={light.kind} size={14} />{/if}
      <Tag tone={tagToneOf(word?.tone ?? 'green')}>{word ? t(`automations.simple.card.word.${word.key}`) : t('automations.simple.card.on')}</Tag>
    </div>
    <h2 class="ap-dr-name" data-dr-name>{automation.name}</h2>
    <div class="ap-dr-st" data-dr-sentence>{sentence}</div>
    <p class="t-quiet">{metaLine(automation)}</p>
    <p class="t-quiet">{cronWords(automation.trigger.cron)}</p>
    {#if automation.target.kind === 'agent' && asks}<p class="t-quiet">{t('automations.simple.dr.asks', { what: asks })}</p>{/if}
    <p class="t-quiet">{t(automation.spends ? 'automations.simple.dr.spends' : 'automations.simple.dr.spends_none')}</p>
    <p class="t-quiet">{t('automations.simple.dr.open_adv_note')}</p>
  {/snippet}
  {#snippet foot()}
    <Switch
      label={t(enabled ? 'automations.simple.card.on' : 'automations.simple.card.off')}
      aria-label={t('automations.simple.card.switch_aria', { name: automation.name })}
      data-dr-switch={id}
      bind:checked={() => enabled, (next) => void setEnabled(automation, next)}
    />
    <Button size="sm" data-dr-run-now={id} onclick={() => void runNow(automation)}>{t('automations.simple.dr.run_now')}</Button>
    <Button size="sm" data-dr-edit={id} onclick={edit}>{t('automations.simple.dr.edit')}</Button>
    <Button size="sm" data-dr-adv={id} onclick={() => openInAdvanced('automation', id)}>{t('automations.simple.dr.open_adv')}</Button>
  {/snippet}
</Card>

{#if !mine || dr.status === 'loading'}
  <Card title={t('automations.simple.dr.last_run')} compact>
    {#snippet children()}<State kind="loading" inline title={t('automations.loading')} data-dr-loading />{/snippet}
  </Card>
{:else if dr.status === 'error'}
  <Card title={t('automations.simple.dr.last_run')} compact>
    {#snippet children()}<State kind="error" inline title={`${t('automations.simple.read_failed')}: ${dr.error}`} data-dr-failed />{/snippet}
    {#snippet foot()}<Button size="sm" onclick={() => void loadAutomation(id, automation.trigger.cron, automation.next_fire_at, automation.enabled)}>{t('automations.simple.retry')}</Button>{/snippet}
  </Card>
{:else if last}
  <LastRun run={last} title={t('automations.simple.dr.last_run')} openable />
{:else}
  <Card title={t('automations.simple.dr.last_run')} compact>
    {#snippet children()}<p class="t-quiet">{t('automations.simple.dr.never_ran')}</p>{/snippet}
  </Card>
{/if}

<Card title={t('automations.simple.dr.next_three')} compact>
  {#snippet children()}
    {#if dr.fires.length && mine}
      <List label={t('automations.simple.dr.next_three')} data-dr-fires>
        {#each dr.fires as fire (fire)}
          <ListRow primary={fireText(clock, fire, dr.fires)} meta={clock.rel(fire, data.now)} />
        {/each}
      </List>
    {:else if mine && dr.status === 'ready'}
      <p class="t-quiet">{t(enabled ? 'automations.simple.dr.nothing_scheduled' : 'automations.simple.dr.off_nothing')}</p>
    {/if}
  {/snippet}
</Card>
