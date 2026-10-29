
<script lang="ts">
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import NumberField from '../base/NumberField.svelte';
  import Select from '../base/Select.svelte';
  import { t } from '../i18n/index.svelte';
  import { editorDraft, MAX_HOURS, REPEAT_KINDS, type EditorDraft, type RepeatKind } from '../../cplugs/huddle/task-manager-schedule';
  import type { WritableSchedule } from '../task-manager-schedules/scheduled-api';

  interface Props {
    schedule: WritableSchedule;
    busy: boolean;
    onSave: (draft: EditorDraft) => void;
    onCancel: () => void;
  }
  const { schedule, busy, onSave, onCancel }: Props = $props();

  const PICK_KEY: Record<RepeatKind, string> = {
    none: 'cplug.huddle.schedule.repeat_none',
    daily: 'cplug.huddle.schedule.repeat_daily_pick',
    weekly: 'cplug.huddle.schedule.repeat_weekly_pick',
    hours: 'cplug.huddle.schedule.repeat_hours_pick',
    monthly: 'cplug.huddle.schedule.repeat_monthly_pick',
  };
  const DAYS = [0, 1, 2, 3, 4, 5, 6].map((day) => ({ day, name: new Date(2026, 9, 5 + day).toLocaleDateString(undefined, { weekday: 'short' }).toLowerCase() }));

  // svelte-ignore state_referenced_locally
  let draft = $state<EditorDraft>(editorDraft(schedule.source, new Date()));

  function pickKind(kind: RepeatKind): void {
    draft.plan.kind = kind;
    if (kind === 'monthly' && !schedule.repeat) draft.plan.monthday = Number(draft.when.slice(8, 10)) || 1;
  }

  function toggleDay(day: number): void {
    draft.plan.days = draft.plan.days.includes(day) ? draft.plan.days.filter((d) => d !== day) : [...draft.plan.days, day].sort();
  }
</script>

<div class="auto-sched__panel" data-sched="editor">
  <div class="auto-sched__field">
    <Field label={t('cplug.huddle.schedule.editor_when')} type="datetime-local" bind:value={draft.when} aria-label={t('cplug.huddle.schedule.picker')} data-sched="when" />
  </div>
  <div class="auto-sched__field">
    <span class="oc-label">{t('cplug.huddle.schedule.repeat')}</span>
    <div class="auto-sched__repeat">
      <Select value={draft.plan.kind} aria-label={t('cplug.huddle.schedule.repeat')} data-sched="kind"
        options={REPEAT_KINDS.map((kind) => ({ value: kind, label: t(PICK_KEY[kind]) }))}
        onchange={(event) => pickKind(event.currentTarget.value as RepeatKind)} />
      {#if draft.plan.kind === 'hours'}
        <NumberField min={1} max={MAX_HOURS} bind:value={draft.plan.hours}
          aria-label={t('cplug.huddle.schedule.hours')} data-sched="hours" />
      {/if}
      {#if draft.plan.kind === 'monthly'}
        <NumberField min={1} max={31} bind:value={draft.plan.monthday}
          aria-label={t('cplug.huddle.schedule.repeat_monthly_pick')} data-sched="monthday" />
      {/if}
    </div>
    {#if draft.plan.kind === 'weekly'}
      <div class="auto-sched__repeat" role="group" aria-label={t('cplug.huddle.schedule.days')}>
        {#each DAYS as one (one.day)}
          <Button size="sm" aria-pressed={draft.plan.days.includes(one.day)}
            data-sched-day={one.day} onclick={() => toggleDay(one.day)}>{one.name}</Button>
        {/each}
      </div>
    {/if}
  </div>
  <div class="auto-sched__actions">
    <Button data-sched="edit-cancel" disabled={busy} onclick={onCancel}>{t('automations.sched.cancel')}</Button>
    <Button variant="confirm" data-sched="save" disabled={busy} onclick={() => onSave(draft)}>{t('automations.sched.save')}</Button>
  </div>
</div>
