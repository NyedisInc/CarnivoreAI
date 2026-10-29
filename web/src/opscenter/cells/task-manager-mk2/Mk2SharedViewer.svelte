<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import { buttonAttrs } from '../../../lib/base/classes';
  import { titleWhenTruncated } from '../../../lib/base/truncate';
  import Icon from '../../ui/Icon.svelte';
  import Select from '../../../lib/base/Select.svelte';
  import TaskManagerArtifactCard from '../../../cplugs/huddle/TaskManagerArtifactCard.svelte';
  import TaskManagerFiles from '../../../cplugs/huddle/TaskManagerFiles.svelte';
  import TaskManagerRoundCard from '../../../cplugs/huddle/TaskManagerRoundCard.svelte';
  import { webLink, type Resource, type Tab } from '../../../cplugs/huddle/task-manager-design/model';

  let { itemId, resource, backTab, version = $bindable(''), onBack, onSource }: {
    itemId: number; resource: Resource; backTab: Tab; version?: string; onBack: () => void; onSource: (resource: Resource) => void;
  } = $props();
</script>

<div class="tm-resource-viewer">
  <button type="button" class="tn-chip" use:titleWhenTruncated {...buttonAttrs('secondary', 'sm')} onclick={onBack}><Icon name="chevron-left" size={12} strokeWidth={2} />{t('cplug.huddle.tm.back_to', { tab: t(`cplug.huddle.tm.tab_${backTab}`) })}</button>
  <h3>{resource.name}</h3>
  {#if resource.versions}<label class="tn-subtle">{t('opscenter.cell.task_manager_mk2.revision')} <Select aria-label={t('opscenter.cell.task_manager_mk2.revision_label')} bind:value={version} options={resource.versions.map((option) => ({ value: option.rev, label: `${option.rev} · ${option.label}` }))} /></label>{/if}
  {#if resource.unavailable}<p class="tn-tag">{resource.reason ?? t('opscenter.cell.task_manager_mk2.resource_unavailable')}</p>
  {:else if resource.shared?.artifact}<TaskManagerArtifactCard {itemId} artifact={resource.shared.artifact} />
  {:else if resource.shared?.file}<TaskManagerFiles {itemId} files={[resource.shared.file]} />
  {:else if resource.shared?.round}<TaskManagerRoundCard round={resource.shared.round} text="" />
  {:else if webLink(resource.href)}<a class="tn-resource" use:titleWhenTruncated {...buttonAttrs('secondary', 'sm')} href={webLink(resource.href)} target="_blank" rel="noopener noreferrer">{t('cplug.huddle.tm.open_actual', { type: resource.type ?? 'resource' })}<Icon name="external" size={12} strokeWidth={2} /></a>
  {:else}<pre class="tm-resource-copy">{resource.versions?.find(v => v.rev === version)?.text ?? resource.text ?? t('opscenter.cell.task_manager_mk2.no_preview')}</pre>{/if}
  {#if Number.isInteger(resource.source)}<button type="button" class="tn-chip" use:titleWhenTruncated {...buttonAttrs('secondary', 'sm')} onclick={() => onSource(resource)}>{t('cplug.huddle.tm.view_in_conversation')}</button>{/if}
</div>
