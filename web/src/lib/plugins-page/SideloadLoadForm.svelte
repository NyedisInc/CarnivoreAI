
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import type { Translate } from '../sessions/types';
    import { refusalText, type GitRequest } from './sideload-switch';
    import './plugin-pane.css';

    interface Props {
        mode: 'folder' | 'git';
        t: Translate;
        onFolder: (path: string, name: string | null) => Promise<void>;
        onGit: (request: GitRequest) => Promise<void>;
        onDone: () => void;
    }

    const { mode, t, onFolder, onGit, onDone }: Props = $props();

    let path = $state('');
    let url = $state('');
    let ref = $state('');
    let subdir = $state('');
    let name = $state('');
    let busy = $state(false);
    let error = $state<string | null>(null);

    const ready = $derived((mode === 'folder' ? path : url).trim() !== '' && !busy);
    const source = $derived((mode === 'folder' ? path : url).trim() || t('plugins.page.sideload.warning.load_source'));

    async function submit(event: SubmitEvent): Promise<void> {
        event.preventDefault();
        if (!ready) return;
        busy = true;
        error = null;
        try {
            if (mode === 'folder') await onFolder(path.trim(), name.trim() || null);
            else await onGit({ url: url.trim(), ref, subdir, name });
            onDone();
        } catch (failure) {
            error = refusalText(failure, t);
        } finally {
            busy = false;
        }
    }
</script>

<form class="sideload-form" data-sideload-form={mode} onsubmit={(event) => void submit(event)}>
    <p class="sideload-form__title">{t(mode === 'folder' ? 'plugins.page.sideload.load_folder' : 'plugins.page.sideload.load_git')}</p>
    <div class="sideload-form__fields">
        {#if mode === 'folder'}
            <Field label={t('plugins.page.sideload.field.path')} bind:value={path} placeholder={t('plugins.page.sideload.field.path_placeholder')} data-sideload-path="1" required />
        {:else}
            <Field label={t('plugins.page.sideload.field.url')} bind:value={url} placeholder={t('plugins.page.sideload.field.url_placeholder')} data-sideload-url="1" required />
            <Field label={t('plugins.page.sideload.field.ref')} bind:value={ref} help={t('plugins.page.sideload.field.ref_help')} data-sideload-ref="1" />
            <Field label={t('plugins.page.sideload.field.subdir')} bind:value={subdir} data-sideload-subdir="1" />
        {/if}
        <Field label={t('plugins.page.sideload.field.name')} bind:value={name} help={t('plugins.page.sideload.field.name_help')} data-sideload-name="1" />
    </div>
    <p class="plp-warn plp-danger sideload-form__warning" data-sideload-warning>{t('plugins.page.sideload.warning.load', { source })}</p>
    {#if error}<p class="plp__error" role="alert" data-sideload-error>{error}</p>{/if}
    <div class="sideload-form__foot">
        <Button size="sm" onclick={onDone}>{t('plugins.page.sideload.cancel')}</Button>
        <Button size="sm" variant="confirm" type="submit" disabled={!ready} data-sideload-submit="1">
            {t(busy ? 'plugins.page.sideload.loading' : 'plugins.page.sideload.load')}
        </Button>
    </div>
</form>

<style>
    @layer components {
        .sideload-form {
            display: flex;
            flex-direction: column;
            width: min(380px, 100%);
            font-family: var(--font-mono);
        }

        .sideload-form__title {
            margin: 0;
            padding: var(--oc-space-2) var(--oc-space-3);
            background: var(--oc-ground-titlerow);
            box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
            color: var(--oc-orange);
            font-size: var(--oc-fs-label, 11px);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
        }

        .sideload-form__fields {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
            padding: var(--oc-space-3);
        }

        .sideload-form__warning {
            margin: 0 var(--oc-space-3) var(--oc-space-2);
        }

        .sideload-form__foot {
            display: flex;
            justify-content: flex-end;
            gap: var(--oc-space-2);
            padding: var(--oc-space-2) var(--oc-space-3);
            box-shadow: inset 0 1px 0 0 var(--oc-line-rule);
        }
    }
</style>
