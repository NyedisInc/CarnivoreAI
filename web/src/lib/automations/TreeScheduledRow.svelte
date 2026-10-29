
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import IconButton from '../base/IconButton.svelte';
  import State from '../base/State.svelte';
  import Tag from '../base/Tag.svelte';
  import { repeatLabel, type EditorDraft } from '../../cplugs/huddle/task-manager-schedule';
  import { deleteItem, isWritable, saveSchedule, setPaused, type Fetcher } from '../task-manager-schedules/scheduled-api';
  import type { TaskManagerSchedule } from '../task-manager-schedules/task-manager-scheduled';
  import { refusalText, whenLabel } from './format';
  import ScheduleItemEditor from './ScheduleItemEditor.svelte';

  interface Props {
    schedule: TaskManagerSchedule;
    onOpen?: (list: string, id: number) => void;
    onChanged: () => void | Promise<void>;
    fetcher?: Fetcher;
  }
  const { schedule, onOpen, onChanged, fetcher }: Props = $props();

  let editing = $state(false);
  let confirming = $state(false);
  let busy = $state(false);
  let problem = $state('');

  const when = $derived.by(() => {
    if (schedule.paused) return t('automations.task_manager.paused');
    if (schedule.fireAt === null) return t('automations.next_none');
    return schedule.state === 'failed' ? t('automations.task_manager.failed', { when: whenLabel(schedule.fireAt) }) : whenLabel(schedule.fireAt);
  });

  const repeat = $derived(schedule.repeat ? repeatLabel(schedule.repeat, t) : t('automations.sched.once'));

  async function act(run: () => Promise<unknown>): Promise<boolean> {
    busy = true;
    problem = '';
    let done = false;
    try {
      await run();
      done = true;
    } catch (error) {
      problem = error instanceof Error && error.message === 'invalid_schedule' ? t('automations.sched.invalid') : refusalText(error);
    } finally {
      busy = false;
    }
    await onChanged();
    return done;
  }

  async function save(draft: EditorDraft): Promise<void> {
    if (isWritable(schedule) && (await act(() => saveSchedule(schedule, draft, fetcher)))) editing = false;
  }
</script>

<li class="ap-st-row" data-task-manager-schedule={schedule.item} data-enabled={schedule.paused ? undefined : ''} data-state={schedule.state}>
  <Button variant="quiet" data-st-name data-tree-open-huddle aria-label={t('automations.task_manager.open_aria', { title: schedule.title })}
    onclick={() => onOpen?.(schedule.list, schedule.item)}>{schedule.title}</Button>
  <span class="ap-st-c-tag"><Tag>{t('automations.tree.task_manager_mark')}</Tag></span>
  <span class="ap-st-when" data-task-manager-schedule-when data-state={schedule.state}>{when}</span>
  <span class="ap-st-rep" data-task-manager-schedule-repeat>{repeat}</span>
  <span class="ap-st-acts">
    {#if isWritable(schedule)}
      {@const writable = schedule}
      {#if schedule.repeat}
        {@const label = t(schedule.paused ? 'automations.sched.resume_aria' : 'automations.sched.pause_aria', { title: schedule.title })}
        <IconButton variant="quiet" label={label} icon={schedule.paused ? 'play' : 'pause'} iconSize={16} data-sched="pause" pressed={schedule.paused} disabled={busy}
          onclick={() => void act(() => setPaused(writable, !schedule.paused, fetcher))} />
      {/if}
      <IconButton variant="quiet" label={t('automations.sched.edit_aria', { title: schedule.title })} icon="pencil" iconSize={16} data-sched="edit"
        aria-expanded={editing} disabled={busy}
        onclick={() => ((confirming = false), (editing = !editing))} />
      <IconButton variant="close" label={t('automations.sched.delete_aria', { title: schedule.title })} icon="trash" iconSize={16} data-sched="delete"
        aria-expanded={confirming} disabled={busy}
        onclick={() => ((editing = false), (confirming = !confirming))} />
    {/if}
  </span>
  {#if isWritable(schedule)}
    {@const writable = schedule}
    {#if editing}
      <ScheduleItemEditor schedule={writable} {busy} onSave={(draft) => void save(draft)} onCancel={() => (editing = false)} />
    {/if}
    {#if confirming}
      <State kind="warn" inline data-sched="warn" title={t('automations.sched.delete_warning', { title: schedule.title })}>
        {#snippet actions()}
          <Button data-sched="cancel" disabled={busy} onclick={() => (confirming = false)}>{t('automations.sched.cancel')}</Button>
          <Button variant="danger" data-sched="confirm" disabled={busy}
            onclick={async () => { if (await act(() => deleteItem(writable, fetcher))) confirming = false; }}>{t('automations.sched.delete_go')}</Button>
        {/snippet}
      </State>
    {/if}
  {/if}
  {#if problem}<p class="auto-line auto-line--error auto-sched__panel" role="alert" data-sched="problem">{problem}</p>{/if}
</li>
