<script lang="ts">
  import GitChip from '../../opscenter/cells/terminal-live/GitChip.svelte';
  import { sessionGit, releaseSessionGit } from '../../opscenter/api/session-git.svelte';
  import type { Resource } from '../../opscenter/api/poll.svelte';
  import type { SessionGitStatus } from '../../opscenter/api/types';
  import { t } from '../i18n/index.svelte';
  import { drawerGit } from './git-view.svelte';

  let res = $state<Resource<SessionGitStatus> | null>(null);

  $effect(() => {
    const id = drawerGit.sessionId;
    if (!id) { res = null; return; }
    res = sessionGit(id);
    return () => releaseSessionGit(id);
  });

  const data = $derived(res?.data ?? null);
  const counts = $derived(
    data?.state === 'ok'
      ? ([['staged', data.counts.staged], ['modified', data.counts.unstaged], ['untracked', data.counts.untracked],
          ['conflicted', data.counts.conflicted]] as const).filter(([, n]) => n > 0)
      : [],
  );
  const note = $derived(data?.state === 'not_a_repo' || data?.state === 'remote' ? t(`git.changes.${data.state}`) : '');
</script>

{#if drawerGit.sessionId}
  <div class="oc-tf fgl" role="group" aria-label={t('git.line.region')} data-git-line="">
    {#if note}
      <span class="oc-tf-label" data-field="note">{note}</span>
    {:else}
      <span class="oc-sf-field fgl-chip" data-field="repo"><GitChip sessionId={drawerGit.sessionId} /></span>
      {#each counts as [key, n] (key)}
        <span class="oc-sf-field" data-field={key}>
          <span class="oc-tf-num">{n}</span><span class="oc-tf-label">{t(`git.line.${key}`)}</span>
        </span>
      {/each}
      {#if data?.state === 'ok' && data.head_short && !data.detached}
        <span class="oc-sf-field" data-field="sha" title={t('git.line.sha_title', { sha: data.head_short })}>
          <span class="oc-tf-num">{data.head_short}</span>
        </span>
      {/if}
    {/if}
  </div>
{/if}

<style>
  @layer components {
    .oc-tf {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 2px 10px;
      padding: 3px var(--oc-space-3);
      min-height: 1.5em;
      background: var(--oc-ground-titlerow);
      border-top: 1px solid var(--oc-line-rule);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      overflow: hidden;
      flex: 0 0 auto;
      box-sizing: border-box;
    }

    .oc-tf > span:not(:first-child) {
      position: relative;
      padding-left: 14px;
    }

    .oc-tf > span:not(:first-child)::before {
      content: '';
      position: absolute;
      left: 3px;
      top: 50%;
      transform: translateY(-50%);
      width: 1px;
      height: 11px;
      background: var(--oc-line-rule);
    }

    .oc-sf-field {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      flex: 0 1 auto;
      min-width: 0;
    }

    .fgl-chip {
      flex: 0 1 auto;
      max-width: 100%;
    }

    .oc-tf-label {
      color: var(--oc-text-dim);
      white-space: nowrap;
      flex: 0 0 auto;
    }

    .oc-tf-num {
      color: var(--oc-text-secondary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }
  }
</style>
