<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import { buttonAttrs } from '../../../lib/base/classes';
  import { titleWhenTruncated } from '../../../lib/base/truncate';
  import Icon from '../../ui/Icon.svelte';
  import TaskManagerMarkdown from '../../../cplugs/huddle/TaskManagerMarkdown.svelte';
  import { webLink, type Resource, type Task } from '../../../cplugs/huddle/task-manager-design/model';
  import { answeredOf } from './mk2-answered';
  import Mk2Crosstalk from './Mk2Crosstalk.svelte';
  import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
  import SharedThumb from '../../../cplugs/huddle/task-manager-design/SharedThumb.svelte';

  let { task, item, onResource, onSource, detailed = false }: { task: Task; item: HuddleItem; onResource: (id: string) => void; onSource: (resource: Resource) => void; detailed?: boolean } = $props();

  const answered = $derived(answeredOf(task.messages));
  const resources = $derived(task.shared ?? task.review?.resources ?? []);
</script>

<div class="tm-details"><div class="tn-overline">{t('cplug.huddle.tm.details_task')}</div><div class="tn-md"><TaskManagerMarkdown text={task.original ?? task.text} /></div><dl><dt>{t('cplug.huddle.tm.project')}</dt><dd>{task.project}</dd><dt>{t('cplug.huddle.tm.agent')}</dt><dd>{task.agent}</dd>{#if task.parent}<dt>{t('cplug.huddle.tm.parent')}</dt><dd>{t('cplug.huddle.tm.task_n', { n: task.parent })}</dd>{/if}{#if answered}<dt>{t('cplug.huddle.tm.answered')}</dt><dd data-mk2-answered={answered.answered ? 'yes' : 'no'}>{answered.answered ? (answered.time ? t('cplug.huddle.tm.answered_yes_at', { time: answered.time }) : t('cplug.huddle.tm.answered_yes')) : t('cplug.huddle.tm.answered_no')}</dd>{/if}</dl>
  {#if task.githubIssue}<a class="tn-resource" use:titleWhenTruncated {...buttonAttrs('secondary', 'sm')} data-mk2-issue href={webLink(task.githubIssue.url)} target="_blank" rel="noopener noreferrer"><Icon name="github" size={12} strokeWidth={2} />{task.githubIssue.repo} #{task.githubIssue.number}<Icon name="external" size={12} strokeWidth={2} /></a>{/if}
  {#if task.note}<div class="tn-overline">{t('cplug.huddle.tm.your_note')}</div><div class="tn-md"><TaskManagerMarkdown text={task.note} /></div>{/if}
  {#if item.from_inbox?.text}<div class="tn-overline">{t('cplug.huddle.tm.add_box_words')}</div><div class="tn-md" data-mk2-add-box-words><TaskManagerMarkdown text={item.from_inbox.text} /></div>{/if}
  <div class="tn-line between"><span class="tn-overline">{t('cplug.huddle.tm.shared_here')}</span><span class="tn-subtle">{t('cplug.huddle.tm.shared_count', { n: resources.length })}</span></div>
  <div class="tm-shared-list">{#each resources as resource}
    <div class="tm-shared-item" data-task-manager-shared={resource.type}><button type="button" class="tm-shared-open" data-btn="row" onclick={() => onResource(resource.id)}>
      {#if resource.type === 'image' && resource.shared?.file}<SharedThumb itemId={task.id} fileId={resource.shared.file.id} />{:else}<Icon name={resource.type === 'board' ? 'components' : resource.type === 'link' ? 'link' : 'docs'} size={16} strokeWidth={2} />{/if}
      <span><span>{resource.name}</span><small>{t(`cplug.huddle.tm.kind_${resource.type ?? 'page'}`)} · {resource.rev ?? t('cplug.huddle.tm.rev_current')}{resource.unavailable ? ` · ${t('cplug.huddle.tm.unavailable')}` : ''}</small></span>
    </button>{#if Number.isInteger(resource.source)}<button type="button" class="tn-chip" use:titleWhenTruncated {...buttonAttrs('secondary', 'sm')} aria-label={t('cplug.huddle.tm.view_named_in_conversation', { name: resource.name })} onclick={() => onSource(resource)}><Icon name="chat" size={12} strokeWidth={2} /></button>{/if}</div>
  {:else}<p class="tn-subtle">{t('cplug.huddle.tm.no_shared')}</p>{/each}</div>
  {#if task.review && (task.review.checks.length || task.review.history.length)}<details open={detailed}><summary>{t('opscenter.cell.task_manager_mk2.review_history')}</summary>{#each task.review.checks as check}<div class="tn-history-event">{t(check.checked ? 'opscenter.cell.task_manager_mk2.check_approved' : 'opscenter.cell.task_manager_mk2.check_outstanding')} · {check.label} · r{check.version}</div>{/each}{#each task.review.history as line}<div class="tn-history-event">{line}</div>{/each}</details>{/if}
  <Mk2Crosstalk {item} />
</div>
