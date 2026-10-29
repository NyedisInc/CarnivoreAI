
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Card from '../../base/Card.svelte';
  import Switch from '../../base/Switch.svelte';
  import Tag from '../../base/Tag.svelte';
  import type { Automation } from '../api';
  import { cronWords } from '../cron-words';
  import { lightOf } from '../logic/marks';
  import type { UnreadState } from '../logic/feed';
  import { data, pageClock } from '../page-store.svelte';
  import Mark from '../Mark.svelte';
  import { metaLine } from './card-meta';
  import { cardTag, cardWord, tagToneOf } from './overview-model';
  import { openCard, overview, setEnabled } from './overview-state.svelte';

  let { automation, unread }: { automation: Automation; unread: UnreadState } = $props();

  const id = $derived(automation.automation_id);
  const enabled = $derived(overview.pending[id] ?? automation.enabled);
  const last = $derived(automation.recent?.[0] ?? null);
  const light = $derived(lightOf(enabled, data.paused, last?.status ?? null));
  const tag = $derived(cardTag(automation, enabled, data.paused, unread, data.now));
  const word = $derived(cardWord(automation, enabled, data.paused));
  const clock = $derived(pageClock());
  const next = $derived(
    !enabled
      ? t('automations.simple.card.next_off')
      : data.paused
        ? t('automations.simple.card.next_paused')
        : automation.next_fire_at
          ? `${clock.rel(automation.next_fire_at, data.now)}, ${clock.short(automation.next_fire_at, data.now)}`
          : '-',
  );
  const meta = $derived(metaLine(automation));

  function pick(event: MouseEvent): void {
    if ((event.target as Element).closest('[role="switch"], button')) return;
    openCard(id);
  }
</script>


<Card title={automation.name} compact data-card={id} data-enabled={enabled} onclick={pick} onopen={() => openCard(id)}>
  {#snippet lead()}
    {#if light.kind === 'run'}<Mark status={light.status} size={12} />{:else}<Mark light={light.kind} size={12} label={light.kind === 'off' && data.paused && enabled ? t('automations.page.sentence.paused') : undefined} />{/if}
  {/snippet}
  {#snippet actions()}
    {#if tag}<Tag tone={tagToneOf(tag.tone)}>{t(`automations.simple.tag.${tag.key}`, { n: tag.n })}</Tag>{/if}
    <Switch
      label={t(enabled ? 'automations.simple.card.on' : 'automations.simple.card.off')}
      aria-label={t('automations.simple.card.switch_aria', { name: automation.name })}
      data-card-switch={id}
      bind:checked={() => enabled, (next) => void setEnabled(automation, next)}
    />
  {/snippet}
  {#snippet children()}
    <p class="t-quiet">{meta}</p>
  {/snippet}
  {#snippet foot()}
    <span class="t-card__when">{cronWords(automation.trigger.cron)} <span class="t-quiet">· {t('automations.simple.card.next', { when: next })}</span></span>
    <span class="t-card__end">
      {#if word}<Tag tone={tagToneOf(word.tone)}>{t(`automations.simple.card.word.${word.key}`)}</Tag>{/if}
    </span>
  {/snippet}
</Card>
