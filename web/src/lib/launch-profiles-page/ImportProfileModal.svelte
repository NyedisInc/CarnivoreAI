
<script lang="ts">
    import ModalShell from '../launchpad/ModalShell.svelte';
    import { Button, Checkbox, Field, State } from '../base';
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
        <Field id="lp-import-text" label={t('launch_profiles.import.paste')} multiline rows={5} data-mono spellcheck="false" disabled={busy}
            bind:value={() => text, (v) => edited(v)} />
        <input type="file" accept="application/json,.json" aria-label={t('launch_profiles.import.file')} disabled={busy} onchange={(e) => void chooseFile(e)} />
        {#if preview}
            <p class="lp-import__label">{t('launch_profiles.import.parts', { name: preview.profile.id })}</p>
            {#if preview.parts.length === 0}<p class="lp-import__note">{t('launch_profiles.import.no_parts')}</p>{/if}
            {#each preview.parts as part, i (i)}
                <p class="lp-import__label">{part.kind}</p>
                <pre class="lp-import__script">{part.text}</pre>
            {/each}
            {#if preview.endpoint_connection_missing}<State inline kind="warn" role="none" title={t('launch_profiles.import.connection_missing')} />{/if}
            {#if preview.exists}
                <Checkbox label={t('launch_profiles.import.replace', { name: preview.profile.id })} bind:checked={replace} data-lp-import-replace />
            {/if}
            <Checkbox label={t('launch_profiles.import.accept')} bind:checked={accepted} data-lp-import-accept />
        {/if}
        {#if error}<State inline kind="error" title={error} />{/if}
    </div>
    {#snippet footer()}
        <Button disabled={busy} data-lp-import-cancel onclick={() => close(null)}>{t('launch_profiles.import.cancel')}</Button>
        <Button disabled={busy || text.trim() === ''} data-lp-import-check onclick={() => void check()}>{t('launch_profiles.import.check')}</Button>
        <Button variant="confirm" disabled={!canImport} data-lp-import-go onclick={() => void submit()}>{t('launch_profiles.import.go')}</Button>
    {/snippet}
</ModalShell>

<style>
  @layer components {
    .lp-import { display: flex; flex-direction: column; gap: 8px; min-width: 0; max-height: 60vh; overflow-y: auto; }
    .lp-import__note { margin: 0; color: var(--oc-text-secondary); font-size: 12px; }
    .lp-import__label { color: var(--oc-text-muted); font-size: 10px; letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }
    .lp-import :global(textarea[data-field][data-mono]) { font-family: var(--font-mono); }
    .lp-import__script { max-height: 30vh; overflow: auto; margin: 0; padding: 8px; border: 1px solid var(--oc-line-rule); border-radius: 2px; background: var(--oc-ground-field); color: var(--oc-text-primary); font-family: var(--font-mono); font-size: 11px; white-space: pre-wrap; overflow-wrap: anywhere; }
  }
</style>
