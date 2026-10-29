
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
    import StatTile from '../../base/StatTile.svelte';
  import { data, pageClock } from '../page-store.svelte';
  import { unread } from '../read-state.svelte';
  import { tileValues } from './overview-model';
  import { jumpToSessions } from './overview-state.svelte';

  const failedRead = $derived(data.status !== 'ready');
  const v = $derived(tileValues(data.automations, data.counts, { seenAt: unread.seenAt, read: new Set(unread.read) }, data.now));
  const clock = $derived(pageClock());
  const none = $derived(data.automations.length === 0);
  const nextValue = $derived(data.paused ? t('automations.simple.tile.next_paused') : v.next ? clock.rel(v.next.at, data.now).replace(/^in /, '') : '-');
  const nextSub = $derived(
    data.paused
      ? t('automations.simple.tile.next_paused_sub')
      : v.next
        ? t('automations.simple.tile.next_named', { name: v.next.name, clock: clock.short(v.next.at, data.now) })
        : t('automations.simple.tile.next_none_sub'),
  );

  let drawn: Record<string, string> = {};
  let ticked = $state<Record<string, boolean>>({});
  const shown = $derived({
    active: String(failedRead ? '-' : v.active),
    next: String(failedRead ? '-' : nextValue),
    needs: String(failedRead ? '-' : v.needs),
    failed: String(failedRead ? '-' : v.failed),
  });
  $effect(() => {
    const now = shown;
    const hits: Record<string, boolean> = {};
    for (const key of Object.keys(now) as (keyof typeof now)[]) if (drawn[key] !== undefined && drawn[key] !== now[key]) hits[key] = true;
    drawn = { ...now };
    ticked = hits;
  });
</script>

<div class="s-tiles" data-overview-tiles>
  <div class="s-tiles__item" data-key="active" data-tick={ticked.active || undefined}>
    <StatTile label={t('automations.simple.tile.active')} figure={String(failedRead ? '-' : v.active)} sub={failedRead ? '' : none ? t('automations.simple.tile.active_none') : t('automations.simple.tile.active_sub', { n: v.total })} />
  </div>
  <div class="s-tiles__item" data-key="next" data-tick={ticked.next || undefined}>
    <StatTile label={t('automations.simple.tile.next')} figure={String(failedRead ? '-' : nextValue)} sub={failedRead ? '' : nextSub} />
  </div>
  <div class="s-tiles__item" data-key="needs" data-tick={ticked.needs || undefined}>
    <StatTile label={t('automations.simple.tile.needs')} figure={String(failedRead ? '-' : v.needs)} sub={failedRead ? '' : t(v.needs ? 'automations.simple.tile.needs_open' : 'automations.simple.tile.needs_clear')} onsub={() => jumpToSessions('needs')} subAttrs={{ 'data-tile-go': 'needs' }} />
  </div>
  <div class="s-tiles__item" data-key="failed" data-tick={ticked.failed || undefined}>
    <StatTile label={t('automations.simple.tile.failed')} figure={String(failedRead ? '-' : v.failed)} sub={failedRead ? '' : t(v.failed ? 'automations.simple.tile.failed_see' : 'automations.simple.tile.failed_none')} onsub={() => jumpToSessions('failed')} subAttrs={{ 'data-tile-go': 'failed' }} />
  </div>
</div>
