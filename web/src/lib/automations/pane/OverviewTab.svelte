
<script lang="ts">
  import Fold from '../../base/Fold.svelte';
  import { t } from '../../i18n/index.svelte';
  import Card from '../../base/Card.svelte';
  import List from '../../base/List.svelte';
  import ListRow from '../../base/ListRow.svelte';
  import Tag from '../../base/Tag.svelte';
  import * as api from '../api';
  import { cronWords } from '../cron-words';
  import { actorLabel, valueLabel } from '../format';
  import { kindWords } from '../list-state.svelte';
  import { codeWords, secsWords } from '../logic/words';
  import { data, pageClock, sessionOptions, wantSessions } from '../page-store.svelte';
  import { pane } from './pane-data.svelte';

  let { automation }: { automation: api.Automation } = $props();

  let fires = $state<string[]>([]);
  let changes = $state<api.AutomationChange[]>([]);
  const clock = $derived(pageClock());

  $effect(() => {
    const cron = automation.trigger.cron;
    const on = automation.enabled;
    fires = [];
    if (!on) return;
    let current = true;
    void api
      .previewSchedule(cron)
      .then((answer) => {
        if (current && answer.ok) fires = answer.fires.slice(0, 5).map((f) => clock.whenLong(Date.parse(f.utc) / 1000));
      })
      .catch(() => {
      });
    return () => (current = false);
  });

  $effect(() => {
    const id = automation.automation_id;
    void automation.revision;
    let current = true;
    void api
      .listChanges(id, 20)
      .then((answer) => {
        if (current) changes = answer.changes;
      })
      .catch(() => {
        if (current) changes = [];
      });
    return () => (current = false);
  });

  $effect(() => {
    if (automation.files_under?.session_uuid && !data.sessions.length) void wantSessions();
  });

  const text = $derived.by(() => {
    const target = automation.target as unknown as Record<string, unknown>;
    const main = ['prompt', 'command', 'title', 'text', 'recipe'].find((k) => typeof target[k] === 'string' && target[k] !== '');
    const chips = Object.entries(target)
      .filter(([k, v]) => k !== 'kind' && k !== main && (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') && v !== '')
      .map(([k, v]) => [k.replace(/_/g, ' '), String(v)] as const);
    return { text: main ? String(target[main]) : '', chips };
  });

  const hosts = $derived([...new Set(pane.runs.map((r) => r.host).filter((h): h is string => !!h))]);
  const delivery = $derived(
    !automation.delivery.notify
      ? t('automations.page.pane.alert.none')
      : t('automations.page.pane.alert.on', { when: t(`automations.page.pane.alert.${automation.delivery.notify_on ?? 'default'}`) }),
  );
  const where = $derived.by(() => {
    const f = automation.files_under ?? { session_uuid: null, project_id: null };
    if (f.session_uuid) return sessionOptions().find((s) => s.session_uuid === f.session_uuid)?.label ?? f.session_uuid;
    if (f.project_id != null) return data.projects.find((p) => p.id === f.project_id)?.name ?? String(f.project_id);
    return t('automations.page.feed.unassigned');
  });

  function what(change: api.AutomationChange): string {
    if (change.action !== 'update') return codeWords('automations.change.action', change.action);
    return change.changes.flatMap((f) => targetEdits(f) ?? [`${codeWords('automations.field_name', f.field)}: ${changeValue(f.field, f.before)} ${t('automations.page.pane.ov.to')} ${changeValue(f.field, f.after)}`]).join('; ');
  }

  function targetEdits(f: { field: string; before: unknown; after: unknown }): string[] | null {
    const [a, b] = [f.before, f.after] as Array<Record<string, unknown> | null>;
    if (f.field !== 'target' || !a || !b || typeof a !== 'object' || typeof b !== 'object' || a.kind !== b.kind) return null;
    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])].filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]));
    if (!keys.length) return null;
    const side = (v: unknown) => (v !== null && typeof v === 'object' ? t('automations.value.changed') : valueLabel(v));
    return keys.map((k) => `${k.replace(/_/g, ' ')}: ${side(a[k])} ${t('automations.page.pane.ov.to')} ${side(b[k])}`);
  }

  function changeValue(field: string, value: unknown): string {
    if (value === null || value === undefined || value === '') return valueLabel(value);
    if (field === 'cron' && typeof value === 'string') return `${cronWords(value)} (${value})`;
    if ((field === 'max_runtime_s' || field === 'retry_backoff_s') && typeof value === 'number') return secsWords(value);
    if (field === 'delivery' && typeof value === 'object') {
      const d = value as { notify?: boolean; notify_on?: string };
      return d.notify === false ? t('automations.page.pane.alert.none') : t('automations.page.pane.alert.on', { when: t(`automations.page.pane.alert.${d.notify_on ?? 'default'}`) });
    }
    if (typeof value === 'object') {
      const kind = (value as { kind?: unknown }).kind;
      return typeof kind === 'string' ? kindWords(kind) : t('automations.value.changed');
    }
    return valueLabel(value);
  }
</script>

<Card title={t('automations.page.pane.ov.title')} compact>
  {#snippet children()}
    <dl class="ap-pn-dl" data-overview>
  <dt>{t('automations.page.pane.ov.schedule')}</dt>
  <dd><span>{cronWords(automation.trigger.cron)}</span> <span class="ap-pn-dim ap-num">{automation.trigger.cron}</span></dd>
  <dt>{t('automations.page.pane.ov.next_five')}</dt>
  <dd>
    {#if fires.length}
      <ol class="ap-pn-fires" data-next-five>{#each fires as f, i (i)}<li class="ap-num">{f}</li>{/each}</ol>
    {:else}
      <span class="ap-pn-dim">{automation.enabled ? t('automations.page.pane.ov.none') : t('automations.page.pane.ov.next_off')}</span>
    {/if}
  </dd>
  <dt>{t('automations.page.pane.ov.computer')}</dt>
  <dd>{hosts.length ? hosts.join(', ') : t('automations.page.reader.computer_not_recorded')}</dd>
  <dt>{t('automations.page.pane.ov.what_ran')}</dt>
  <dd>
    {kindWords(automation.target.kind)}
    <Fold label={t('automations.page.pane.ov.show_what')}>
      {#snippet children()}
        {#if text.text}<pre class="r-pre">{text.text}</pre>{/if}
        {#if text.chips.length}
          <div class="ap-pn-chips">{#each text.chips as [k, v] (k)}<Tag><i>{k}</i> {v}</Tag>{/each}</div>
        {/if}
      {/snippet}
    </Fold>
  </dd>
  <dt>{t('automations.page.pane.ov.delivery')}</dt>
  <dd>{delivery}</dd>
  <dt>{t('automations.page.pane.ov.missed')}</dt>
  <dd>{codeWords('automations.misfire', automation.misfire)}</dd>
  <dt>{t('automations.page.pane.ov.retries')}</dt>
  <dd>{automation.retry_max ? t('automations.page.pane.ov.retries_value', { retries: automation.retry_max === 1 ? t('automations.page.pane.ov.retry_one') : t('automations.page.pane.ov.retry_many', { n: automation.retry_max }), mins: Math.round(automation.retry_backoff_s / 60) }) : t('automations.page.pane.ov.retries_none')}</dd>
  <dt>{t('automations.page.pane.ov.max_runtime')}</dt>
  <dd>{automation.max_runtime_s ? secsWords(automation.max_runtime_s) : t('automations.page.pane.ov.no_limit')}</dd>
  <dt>{t('automations.page.pane.ov.project')}</dt>
  <dd data-overview-project>{where}</dd>
  <dt>{t('automations.page.pane.ov.made_by')}</dt>
  <dd>{actorLabel(automation.created_actor)}, {clock.when(automation.created_at)}</dd>
  <dt>{t('automations.page.pane.ov.last_changed')}</dt>
  <dd>{actorLabel(automation.updated_actor)}, {clock.when(automation.updated_at)}</dd>
</dl>
  {/snippet}
</Card>

<Card title={t('automations.page.pane.ov.change_log')} compact>
  {#snippet children()}
    {#if changes.length === 0}
      <p class="ap-pn-one ap-pn-dim" data-changes-empty>{t('automations.changes_empty')}</p>
    {:else}
      <List label={t('automations.page.pane.ov.change_log')} data-change-log>
        {#each changes.slice(0, 20) as change (change.seq)}
          <ListRow wrap data-change={String(change.seq)} primary={what(change)} secondary={t('automations.page.pane.ov.by', { who: actorLabel(change.actor) })} meta={clock.when(change.at)} />
        {/each}
      </List>
    {/if}
  {/snippet}
</Card>
