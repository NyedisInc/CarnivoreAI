
<script lang="ts">
    import { onMount } from 'svelte';
    import { Button, Field } from '../base';
    import Check from '../../opscenter/ui/Check.svelte';
    import type { Translate } from '../sessions/types';
    import { branchFromName, createWorktreeApi, initialCopy, worktreeAnswer, type WorktreeAnswer, type WorktreeApi, type WorktreeProbe } from './worktree-model';

    interface Props {
        t: Translate;
        folder: string;
        name?: string;
        answer: WorktreeAnswer | null;
        api?: WorktreeApi;
    }
    let { t, folder, name = '', answer = $bindable(), api: injected }: Props = $props();
    // svelte-ignore state_referenced_locally
    const api: WorktreeApi = injected ?? createWorktreeApi();

    let probe = $state<WorktreeProbe | null>(null);
    let on = $state(false);
    let branch = $state('');
    let branchTouched = $state(false);
    let base = $state('');
    let setup = $state(false);
    let copy = $state<string[]>([]);
    let approving = $state(false);
    let failure = $state('');

    onMount(() => {
        let live = true;
        api.probe(folder).then((p) => {
            if (!live) return;
            probe = p;
            base = p.current ?? '';
            copy = initialCopy(p);
        }).catch(() => { if (live) probe = null; });
        return () => { live = false; };
    });

    $effect(() => { if (!branchTouched) branch = branchFromName(name); });
    $effect(() => { answer = worktreeAnswer(on, branch, base, setup && !!probe?.file?.approved, copy); });

    function toggleCopy(file: string, next: boolean): void {
        copy = next ? [...copy, file] : copy.filter((c) => c !== file);
    }

    async function approve(): Promise<void> {
        const file = probe?.file;
        if (!file || !probe?.toplevel) return;
        approving = true; failure = '';
        try {
            await api.approve(probe.toplevel, file.sha256);
            probe = { ...probe, file: { ...file, approved: true } };
            setup = true;
        } catch (err) {
            failure = err instanceof Error ? err.message : String(err);
        }
        approving = false;
    }
</script>

{#if probe?.repo}
    <div class="lwt" data-launch-worktree>
        <Check id="lwt-on" data-lwt-on="" label={t('launch_picker.worktree.on')} checked={on} onToggle={(next) => (on = next)} />
        {#if on}
            <label class="lwt-label" for="lwt-branch">{t('launch_picker.worktree.branch')}</label>
            <Field id="lwt-branch" block type="text" spellcheck="false" autocomplete="off" bind:value={branch} oninput={() => (branchTouched = true)} data-lwt-branch />
            <label class="lwt-label" for="lwt-base">{t('launch_picker.worktree.base')}</label>
            <Field id="lwt-base" block type="text" list="lwt-bases" spellcheck="false" autocomplete="off" bind:value={base} data-lwt-base />
            <datalist id="lwt-bases">{#each probe.branches ?? [] as b (b)}<option value={b}></option>{/each}</datalist>
            {#if probe.file_error}<p class="lwt-error" role="alert">{probe.file_error}</p>{/if}
            {#if probe.file}
                {#if probe.file.setup.length}
                    {#if probe.file.approved}
                        <Check id="lwt-setup" data-lwt-setup="" label={t('launch_picker.worktree.setup')} checked={setup} onToggle={(next) => (setup = next)} />
                    {:else}
                        <p class="lwt-note">{t('launch_picker.worktree.approve_note')}</p>
                        <pre class="lwt-file" data-lwt-file>{probe.file.text}</pre>
                        <div><Button disabled={approving} data-lwt-approve onclick={approve}>{t('launch_picker.worktree.approve')}</Button></div>
                        {#if failure}<p class="lwt-error" role="alert">{failure}</p>{/if}
                    {/if}
                {/if}
                {#if probe.file.copy.length}
                    <span class="lwt-label">{t('launch_picker.worktree.copy')}</span>
                    {#each probe.file.copy as c (c.name)}
                        <Check id={`lwt-copy-${c.name}`} data-lwt-copy={c.name} label={c.secret ? t('launch_picker.worktree.copy_secret', { name: c.name }) : c.name} checked={copy.includes(c.name)} onToggle={(next) => toggleCopy(c.name, next)} />
                    {/each}
                {/if}
            {/if}
        {/if}
    </div>
{/if}

<style>
  @layer components {
    .lwt { display: flex; flex-direction: column; gap: var(--oc-space-1); min-width: 0; font-family: var(--font-mono); }
    .lwt-label { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }
    .lwt-note { margin: 0; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); overflow-wrap: anywhere; }
    .lwt-file { margin: 0; padding: var(--oc-space-1); max-height: 160px; overflow: auto; border-left: 2px solid var(--oc-orange); background: var(--oc-ground-field); color: var(--oc-text-primary); font-size: var(--oc-fs-micro); white-space: pre-wrap; overflow-wrap: anywhere; }
    .lwt-error { margin: 0; padding: var(--oc-space-1); border-left: 2px solid var(--oc-coral); background: var(--oc-ground-field); color: var(--oc-text-primary); font-size: var(--oc-fs-micro); overflow-wrap: anywhere; }
    @media (max-width: 767px) {
      .lwt :global([data-lwt-on]), .lwt :global([data-lwt-setup]) { min-height: 44px; }
    }
  }
</style>
