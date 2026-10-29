<!-- and writes nothing -->
<script lang="ts">
    import ModalShell from '../launchpad/ModalShell.svelte';
    import type { Translate } from '../sessions/types';
    import { errorText, type ImportPreview, type LaunchProfilesApi } from './api';

    interface Props {
        api: LaunchProfilesApi;
        t: Translate;
        close: (value: string | null) => void;
    }
    const { api, t, close }: Props = $props();

    let text = $state('');
    let preview = $state<ImportPreview | null>(null);
    let checked: unknown = null;
    let busy = $state(false);
    let error = $state('');
    let accepted = $state(false);
    let replace = $state(false);

    const canImport = $derived(!busy && !!preview && accepted && (!preview.exists || replace));

    function edited(next: string): void {
        text = next; preview = null; checked = null; accepted = false; replace = false; error = '';
    }

    async function chooseFile(event: Event): Promise<void> {
        const file = (event.currentTarget as HTMLInputElement).files?.[0];
        if (file) edited(await file.text());
    }

    async function check(): Promise<void> {
        if (busy) return;
        let doc: unknown;
        try { doc = JSON.parse(text); } catch { error = t('launch_profiles.import.not_json'); return; }
        busy = true; error = '';
        try { preview = await api.importPreview(doc); checked = doc; }
        catch (err) { preview = null; error = t('launch_profiles.import.refused', { reason: errorText(err) }); }
        busy = false;
    }

    async function submit(): Promise<void> {
        if (!canImport || !preview) return;
        busy = true; error = '';
        try { const out = await api.importDoc(checked, preview.sha256, preview.exists && replace); busy = false; close(out.profile.id); }
        catch (err) { busy = false; error = t('launch_profiles.import.refused', { reason: errorText(err) }); }
    }
</script>

<ModalShell title={t('launch_profiles.import.title')} dismissable={!busy} onCancel={() => close(null)}>
    <div class="lp-import" data-lp-import>
        <p class="lp-import__note">{t('launch_profiles.import.lead')}</p>
        <label class="lp-import__label" for="lp-import-text">{t('launch_profiles.import.paste')}</label>
        <textarea id="lp-import-text" class="lp-import__text" rows="5" spellcheck="false" disabled={busy} value={text} oninput={(e) => edited((e.currentTarget as HTMLTextAreaElement).value)}></textarea>
        <input type="file" accept="application/json,.json" aria-label={t('launch_profiles.import.file')} disabled={busy} onchange={(e) => void chooseFile(e)} />
        {#if preview}
            <p class="lp-import__label">{t('launch_profiles.import.parts', { name: preview.profile.id })}</p>
            {#if preview.parts.length === 0}<p class="lp-import__note">{t('launch_profiles.import.no_parts')}</p>{/if}
            {#each preview.parts as part, i (i)}
                <p class="lp-import__label">{part.kind}</p>
                <pre class="lp-import__script">{part.text}</pre>
            {/each}
            {#if preview.endpoint_connection_missing}<p class="lp-import__warn">{t('launch_profiles.import.connection_missing')}</p>{/if}
            {#if preview.exists}
                <label class="lp-import__check"><input type="checkbox" bind:checked={replace} /> {t('launch_profiles.import.replace', { name: preview.profile.id })}</label>
            {/if}
            <label class="lp-import__check"><input type="checkbox" bind:checked={accepted} /> {t('launch_profiles.import.accept')}</label>
        {/if}
        {#if error}<p class="lp-import__error" role="alert">{error}</p>{/if}
    </div>
    {#snippet footer()}
        <button type="button" class="modal-btn modal-btn-secondary" disabled={busy} onclick={() => close(null)}>{t('launch_profiles.import.cancel')}</button>
        <button type="button" class="modal-btn modal-btn-secondary" disabled={busy || text.trim() === ''} onclick={() => void check()}>{t('launch_profiles.import.check')}</button>
        <button type="button" class="modal-btn modal-btn-confirm" disabled={!canImport} onclick={() => void submit()}>{t('launch_profiles.import.go')}</button>
    {/snippet}
</ModalShell>

<style>
  @layer components {
    .lp-import { display: flex; flex-direction: column; gap: 8px; min-width: 0; max-height: 60vh; overflow-y: auto; }
    .lp-import__note { margin: 0; color: var(--oc-text-secondary); font-size: 12px; }
    .lp-import__label { color: var(--oc-text-muted); font-size: 10px; letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }
    .lp-import__text { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid var(--oc-line-rule); border-radius: 2px; background: var(--oc-ground-field); color: var(--oc-text-primary); font-family: var(--font-mono); font-size: 11px; }
    .lp-import__script { max-height: 30vh; overflow: auto; margin: 0; padding: 8px; border: 1px solid var(--oc-line-rule); border-radius: 2px; background: var(--oc-ground-field); color: var(--oc-text-primary); font-family: var(--font-mono); font-size: 11px; white-space: pre-wrap; overflow-wrap: anywhere; }
    .lp-import__check { display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--oc-text-primary); }
    .lp-import__warn, .lp-import__error { margin: 0; padding: 6px 8px; border-left: 2px solid var(--oc-yellow); background: var(--oc-ground-field); color: var(--oc-text-primary); font-size: 12px; overflow-wrap: anywhere; }
    .lp-import__error { border-left-color: var(--oc-coral); }
  }
</style>
