<script lang="ts">
  import { tick } from 'svelte';
  import { baseField } from './task-manager-base-field';
  import { t } from '../sdk';
  import { closeScheduleEditor, pickEditorProject, runEditorNow, saveEditor, scheduleEditor } from './task-manager-schedule-editor.svelte';
  import { huddle } from './huddle.svelte';
  import { listLabel, projectChoices } from './task-manager-schedule-project';
  import { MAX_HOURS, REPEAT_KINDS, editorDraft, type EditorDraft, type RepeatKind } from './task-manager-schedule';

  const PICK_KEY: Record<RepeatKind, string> = {
    none: 'cplug.huddle.schedule.repeat_none', daily: 'cplug.huddle.schedule.repeat_daily_pick', weekly: 'cplug.huddle.schedule.repeat_weekly_pick',
    hours: 'cplug.huddle.schedule.repeat_hours_pick', monthly: 'cplug.huddle.schedule.repeat_monthly_pick',
  };
  const DAYS = [0, 1, 2, 3, 4, 5, 6].map((day) => ({ day, name: new Date(2026, 9, 5 + day).toLocaleDateString(undefined, { weekday: 'short' }).toLowerCase() }));

  const item = $derived(scheduleEditor.item);
  const key = $derived(item ? String(item.id) : 'new');
  const choices = $derived(projectChoices(huddle.lists));
  const projectName = $derived(listLabel(scheduleEditor.list, huddle.lists.find((row) => row.key === scheduleEditor.list)?.name ?? null));
  let draft = $state<EditorDraft>(editorDraft(null, new Date()));
  let busy = $state(false);
  let first = $state<HTMLElement | null>(null);

  $effect(() => {
    if (!scheduleEditor.open) return;
    draft = editorDraft(item, new Date());
    busy = false;
    void tick().then(() => first?.focus());
  });

  function pickKind(kind: RepeatKind): void {
    draft.plan.kind = kind;
    if (kind === 'monthly' && !item?.start_trigger?.repeat) draft.plan.monthday = Number(draft.when.slice(8, 10)) || 1;
  }

  function toggleDay(day: number): void {
    draft.plan.days = draft.plan.days.includes(day) ? draft.plan.days.filter((d) => d !== day) : [...draft.plan.days, day].sort();
  }

  async function finish(action: (d: EditorDraft) => Promise<boolean>): Promise<void> {
    if (busy) return;
    busy = true;
    const done = await action(draft);
    busy = false;
    if (done) closeScheduleEditor();
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeScheduleEditor();
    }
  }
</script>

{#if scheduleEditor.open}
  <div class="hse popup-focus" role="dialog" tabindex="-1" aria-label={t(item ? 'cplug.huddle.schedule.editor_edit' : 'cplug.huddle.schedule.editor_add')}
       data-task-manager-schedule-editor={key} onkeydown={onKeydown}>
    <div class="hse-titlerow"><span class="hse-label">{t(item ? 'cplug.huddle.schedule.editor_edit' : 'cplug.huddle.schedule.editor_add')}</span></div>
    <div class="hse-body">
      <label class="hse-field">
        <span class="hse-label">{t('cplug.huddle.schedule.editor_project')}</span>
        {#if item}
          
          <span class="hse-fixed" data-task-manager-schedule-project-fixed={key}>{projectName}</span>
        {:else}
          <select class="oc-field" value={scheduleEditor.list} data-task-manager-schedule-project={key}
                  onchange={(event) => pickEditorProject(event.currentTarget.value)}>
            {#each choices as row (row.key)}<option value={row.key}>{listLabel(row.key, row.name)}</option>{/each}
          </select>
        {/if}
      </label>
      <label class="hse-field">
        <span class="hse-label">{t('cplug.huddle.schedule.editor_title')}</span>
        <input class="oc-field" use:baseField type="text" bind:value={draft.title} data-task-manager-schedule-title={key} />
      </label>
      <label class="hse-field">
        <span class="hse-label">{t('cplug.huddle.schedule.editor_text')}</span>
        <textarea class="oc-field hse-text" use:baseField rows="5" bind:value={draft.text} bind:this={first} data-task-manager-schedule-text={key}
                  placeholder={t('cplug.huddle.schedule.editor_text_hint')}></textarea>
      </label>
      <label class="hse-field">
        <span class="hse-label">{t('cplug.huddle.schedule.editor_when')}</span>
        <input class="oc-field" use:baseField type="datetime-local" bind:value={draft.when} aria-label={t('cplug.huddle.schedule.picker')} data-task-manager-schedule-input={key} />
      </label>
      <div class="hse-field">
        <span class="hse-label">{t('cplug.huddle.schedule.repeat')}</span>
        <div class="hse-repeat">
          <select class="oc-field" value={draft.plan.kind} aria-label={t('cplug.huddle.schedule.repeat')} data-task-manager-repeat-kind={key}
                  onchange={(event) => pickKind(event.currentTarget.value as RepeatKind)}>
            {#each REPEAT_KINDS as kind (kind)}<option value={kind}>{t(PICK_KEY[kind])}</option>{/each}
          </select>
          {#if draft.plan.kind === 'hours'}
            <input class="oc-field hse-number" use:baseField type="number" min="1" max={MAX_HOURS} bind:value={draft.plan.hours}
                   aria-label={t('cplug.huddle.schedule.hours')} data-task-manager-repeat-hours={key} />
          {/if}
          {#if draft.plan.kind === 'monthly'}
            <input class="oc-field hse-number" use:baseField type="number" min="1" max="31" bind:value={draft.plan.monthday}
                   aria-label={t('cplug.huddle.schedule.repeat_monthly_pick')} data-task-manager-repeat-monthday={key} />
          {/if}
        </div>
        {#if draft.plan.kind === 'weekly'}
          <div class="hse-days" role="group" aria-label={t('cplug.huddle.schedule.days')} data-task-manager-repeat-days={key}>
            {#each DAYS as one (one.day)}
              <button type="button" class="oc-btn oc-btn--sm" class:hse-day--on={draft.plan.days.includes(one.day)} aria-pressed={draft.plan.days.includes(one.day)}
                      data-task-manager-repeat-day={one.day} onclick={() => toggleDay(one.day)}>{one.name}</button>
            {/each}
          </div>
        {/if}
      </div>
    </div>
    <footer class="hse-foot">
      <button type="button" class="modal-btn modal-btn-secondary" data-task-manager-schedule-close onclick={closeScheduleEditor}>{t('cplug.huddle.row.note_cancel')}</button>
      <button type="button" class="modal-btn modal-btn-secondary" disabled={busy} data-task-manager-schedule-run={key}
              onclick={() => void finish(runEditorNow)}>{t('cplug.huddle.schedule.run_now')}</button>
      <button type="button" class="modal-btn modal-btn-confirm" disabled={busy} data-task-manager-schedule-save={key}
              onclick={() => void finish(saveEditor)}>{t(item ? 'cplug.huddle.row.note_save' : 'cplug.huddle.schedule.editor_add_key')}</button>
    </footer>
  </div>
{/if}

<style>
  @layer components {
    .hse {
      position: fixed;
      top: 50%;
      left: 50%;
      z-index: 60;
      display: flex;
      flex-direction: column;
      width: min(32rem, calc(100vw - var(--oc-space-5)));
      max-height: calc(100vh - var(--oc-space-5));
      margin: 0;
      padding: 0;
      border-radius: var(--oc-radius-sm);
      overflow: auto;
      transform: translate(-50%, -50%);
    }

    .hse-titlerow {
      display: flex;
      align-items: center;
      min-height: var(--oc-space-5);
      padding: 0 var(--oc-space-3);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .hse-label {
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hse-body {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-3);
      padding: var(--oc-space-3);
    }

    .hse-field {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      min-width: 0;
    }

    .hse-fixed {
      color: var(--oc-text-primary);
      overflow-wrap: anywhere;
    }

    .hse-text {
      resize: vertical;
      font-family: var(--font-mono);
    }

    .hse-repeat,
    .hse-days {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--oc-space-1);
    }

    .hse-number {
      width: 5rem;
    }

    .hse-day--on {
      border-color: var(--oc-cyan);
      color: var(--oc-cyan);
    }

    .hse-foot {
      display: flex;
      justify-content: flex-end;
      gap: var(--oc-space-2);
      padding: var(--oc-space-2) var(--oc-space-3);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }
  }
</style>
