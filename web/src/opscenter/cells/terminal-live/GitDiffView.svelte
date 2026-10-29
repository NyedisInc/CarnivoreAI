<script lang="ts">
  import { authFetch } from '../../api/auth.svelte';
  import type { SessionGitDiff } from '../../api/types';
  import { t } from '../../../lib/i18n/index.svelte';

  let { sessionId, path }: { sessionId: string; path: string } = $props();

  let diff = $state<SessionGitDiff | null>(null);
  let failed = $state<'unknown' | 'gone' | null>(null);

  $effect(() => {
    const id = encodeURIComponent(sessionId);
    const q = encodeURIComponent(path);
    let live = true;
    diff = null;
    failed = null;
    authFetch<SessionGitDiff>(`/sessions/${id}/git-diff?path=${q}`).then(
      (d) => { if (live) diff = d; },
      (e: unknown) => { if (live) failed = (e as { status?: number })?.status === 404 ? 'gone' : 'unknown'; },
    );
    return () => { live = false; };
  });

  function kind(line: string): 'add' | 'del' | 'hunk' | 'meta' | 'ctx' {
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ')) return 'meta';
    if (line.startsWith('@@')) return 'hunk';
    if (line.startsWith('+')) return 'add';
    if (line.startsWith('-')) return 'del';
    return 'ctx';
  }

  const note = $derived<string | null>(
    failed ? t(`git.diff.${failed}`)
      : !diff ? t('git.diff.loading')
      : diff.state !== 'ok' ? t(`git.diff.${diff.state}`)
      : diff.sensitive ? t('git.diff.sensitive')
      : diff.binary ? t('git.diff.binary')
      : diff.directory ? t('git.diff.directory')
      : diff.text === '' ? t('git.diff.empty')
      : null,
  );
  const lines = $derived(diff && note === null ? diff.text.split('\n') : []);
</script>

<div class="oc-gd" data-git-diff-view="" data-state={failed ?? diff?.state ?? 'loading'}>
  {#if diff?.untracked && note === null}<p class="oc-gd-note" data-git-diff-flag="untracked">{t('git.diff.untracked')}</p>{/if}
  {#if note !== null}
    <p class="oc-gd-note" data-git-diff-note="" role="status">{note}</p>
  {:else}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex: a scroll box must be keyboard reachable -->
    <pre class="oc-gd-text" tabindex="0" aria-label={path} data-git-diff-text="">{#each lines as line, i (i)}<span class="oc-gd-line" data-line={kind(line)}>{line}
</span>{/each}</pre>
    {#if diff?.truncated}<p class="oc-gd-note" data-git-diff-flag="truncated">{t('git.diff.truncated')}</p>{/if}
  {/if}
</div>

<style>
  @layer components {
    .oc-gd { display:flex; flex-direction:column; min-height:0; height:100%; font-family:var(--font-mono); font-size:var(--oc-fs-label); color:var(--oc-text-primary); background:var(--oc-ground-field); }

    .oc-gd-note { margin:0; padding:var(--oc-space-2) var(--oc-space-3); color:var(--oc-text-dim); box-shadow:0 1px 0 var(--oc-line-rule); }

    .oc-gd[data-state='unknown'] .oc-gd-note { color:var(--oc-coral); }

    .oc-gd-text { flex:1 1 auto; min-height:0; margin:0; padding:var(--oc-space-1) 0; overflow:auto; white-space:pre; tab-size:4; }

    .oc-gd-text:focus-visible { outline:none; box-shadow:inset 0 0 0 1px var(--oc-orange); }

    .oc-gd-line { display:block; padding:0 var(--oc-space-3); }

    .oc-gd-line[data-line='add'] { color:var(--oc-green); background:var(--oc-ground-hover); }

    .oc-gd-line[data-line='del'] { color:var(--oc-coral); background:var(--oc-ground-hover); }

    .oc-gd-line[data-line='hunk'] { color:var(--oc-orange); }

    .oc-gd-line[data-line='meta'] { color:var(--oc-text-dim); }
  }
</style>
