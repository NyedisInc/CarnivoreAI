
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import ListRow from '../base/ListRow.svelte';
  import Tag from '../base/Tag.svelte';
  import type { PackActivityItem } from './activity-api';
  import type { JobView } from './jobs-api';
  import JobDetails from './JobDetails.svelte';
  import { clockWords, durationWords, stateWord } from './jobs-format';

  interface Props {
    item: PackActivityItem;
    jobView?: JobView;
    canOpenSession?: boolean;
    canOpenStarter?: boolean;
    onOpenSession?: (uuid: string) => void;
    onStopJob?: (job: JobView) => void;
    onFilterComputer?: (installId: string) => void;
  }
  const {
    item, jobView, canOpenSession = false, canOpenStarter = false,
    onOpenSession, onStopJob, onFilterComputer,
  }: Props = $props();

  const kindLabel = $derived(
    item.item_type === 'agent'
      ? t('pack.activity.kind.agent')
      : item.item_type === 'delegated_agent'
        ? t('pack.activity.kind.delegated_agent')
        : t('pack.activity.kind.command'),
  );
  const statusLabel = $derived(
    item.item_type === 'agent' ? item.status : stateWord(item.status),
  );
  const whenText = $derived(
    item.live
      ? t('pack.activity.when.live', { at: clockWords(item.started_at), elapsed: durationWords(item.duration_s) })
      : t('pack.activity.when.done', { dur: durationWords(item.duration_s), at: clockWords(item.started_at) }),
  );
  const computerText = $derived(
    item.source_computer_label && item.source_computer_label !== item.computer_label
      ? `${item.computer_label} ← ${item.source_computer_label}`
      : item.computer_label,
  );
</script>

<ListRow
  wrap
  primary={item.title}
  secondary={item.project || undefined}
  data-activity-row={item.id}
  data-item-type={item.item_type}
  data-live={item.live ? 'true' : 'false'}
>
  {#snippet lead()}
    <span class="pa-lead-tags">
      <Tag tone={item.tone} data-activity="status">{statusLabel}</Tag>
      <Tag tone="neutral" data-activity="kind">{kindLabel}</Tag>
    </span>
  {/snippet}
  {#snippet actions()}
    {#if item.session_uuid && canOpenSession}
      <Button size="sm" data-activity="open" onclick={() => onOpenSession?.(item.session_uuid!)}>
        {t('pack.activity.action.open')}
      </Button>
    {/if}
    {#if item.started_by.session_uuid && canOpenStarter}
      <Button size="sm" data-activity="open-starter" onclick={() => onOpenSession?.(item.started_by.session_uuid!)}>
        {t('pack.activity.action.open_starter')}
      </Button>
    {/if}
    {#if item.can_stop && jobView}
      <Button size="sm" data-activity="stop" onclick={() => onStopJob?.(jobView)}>
        {t('pack.jobs.stop.action')}
      </Button>
    {/if}
  {/snippet}
  {#snippet below()}
    <div class="pa-meta" data-activity="meta">
      <span class="pa-meta__item">
        <span class="pa-meta__k">{t('pack.activity.meta.on')}</span>
        <span class="pa-meta__v" data-activity="computer">{computerText}</span>
      </span>
      <span class="pa-meta__item">
        <span class="pa-meta__k">{t('pack.activity.meta.by')}</span>
        <span class="pa-meta__v" data-activity="starter">{item.started_by.label}</span>
      </span>
      <span class="pa-meta__item">
        <span class="pa-meta__k">{t('pack.activity.meta.when')}</span>
        <span class="pa-meta__v" data-activity="when">{whenText}</span>
      </span>
      {#if item.computer_id && onFilterComputer}
        <Button size="sm" data-activity="only-computer" onclick={() => onFilterComputer(item.computer_id)}>
          {t('pack.activity.action.filter_computer', { name: item.computer_label })}
        </Button>
      {/if}
    </div>
    {#if item.reason}
      <div class="pa-reason" data-activity="reason">{item.reason}</div>
    {/if}
    {#if jobView}
      <JobDetails job={jobView} />
    {/if}
  {/snippet}
</ListRow>
