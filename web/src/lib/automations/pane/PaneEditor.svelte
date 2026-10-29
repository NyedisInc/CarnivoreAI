
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import AutomationEditor from '../AutomationEditor.svelte';
  import type { Automation } from '../api';
  import { startFromTemplate } from '../list-state.svelte';
  import { TEMPLATES, templateNameKey, type Template } from '../logic/templates';
  import { closePane, data, refresh, select } from '../page-store.svelte';

  let { automation }: { automation: Automation | null } = $props();

  let reloads = $state(0);
  let picked = $state<Template['id'] | null>(null);

  async function done(saved: Automation): Promise<void> {
    data.notice = t(automation ? 'automations.page.toast.saved' : 'automations.page.toast.created', { name: saved.name });
    await refresh();
    select(saved.automation_id);
    data.paneMode = null;
    data.paneTab = 'overview';
    data.paneOpen = true;
  }

  /* a new automation */
  function cancel(): void {
    if (automation) data.paneMode = null;
    else closePane();
  }

  async function conflict(): Promise<void> {
    await refresh();
    data.notice = t('automations.page.toast.changed_elsewhere', { name: automation?.name ?? '' });
    reloads += 1;
  }

  function pick(tpl: Template): void {
    picked = tpl.id;
    startFromTemplate(tpl);
  }

  function keys(e: KeyboardEvent): void {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    cancel();
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="ap-pn-edw" data-pane-editor onkeydown={keys}>
  {#if data.targets}
    {#key `${data.seedCount}:${reloads}:${automation?.automation_id ?? ''}`}
      <AutomationEditor {automation} targets={data.targets} projects={data.projects} seed={automation ? null : data.seed} onDone={(saved) => void done(saved)} onCancel={cancel} onConflict={() => void conflict()} onIdea={() => (picked = null)}>
        {#snippet header()}
          {#if !automation}
            <div class="ap-pn-recipes" role="group" aria-label={t('automations.page.editor.templates_aria')}>
              {#each TEMPLATES as tpl (tpl.id)}
                <Button size="sm" data-template={tpl.id} aria-pressed={picked === tpl.id} onclick={() => pick(tpl)}>{t(templateNameKey(tpl))}</Button>
              {/each}
            </div>
          {/if}
        {/snippet}
      </AutomationEditor>
    {/key}
  {/if}
</div>
