
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import Fold from '../base/Fold.svelte';
    import { pluginsStore, type GithubPreviewRequest, type GithubPreviewResponse } from '../plugins/store.svelte';
    import type { Translate } from '../sessions/types';

    interface Props {
        source?: string;
        ref?: string;
        subdir?: string;
        busy?: boolean;
        error?: string | null;
        onPreview?: (req: GithubPreviewRequest) => Promise<unknown> | void;
        onPreviewed?: (preview: GithubPreviewResponse) => void;
        t: Translate;
    }

    let {
        source = $bindable(''),
        ref = $bindable(''),
        subdir = $bindable(''),
        busy = false,
        error = null,
        onPreview,
        onPreviewed,
        t,
    }: Props = $props();

    let advancedOpen = $state(false);
    let internalBusy = $state(false);
    let internalError = $state<string | null>(null);

    const isBusy = $derived(busy || internalBusy);
    const shownError = $derived(error ?? internalError);
    const canPreview = $derived(!isBusy && source.trim().length > 0);

    async function submitPreview(): Promise<void> {
        const trimmedSource = source.trim();
        if (!trimmedSource || isBusy) return;
        const req: GithubPreviewRequest = {
            source: trimmedSource,
            ...(ref.trim() ? { ref: ref.trim() } : {}),
            ...(subdir.trim() ? { subdir: subdir.trim() } : {}),
        };
        if (onPreview) {
            await onPreview(req);
            return;
        }
        internalBusy = true;
        internalError = null;
        try {
            const res = await pluginsStore.previewGithub(req);
            onPreviewed?.(res);
        } catch (err) {
            internalError = err instanceof Error ? err.message : String(err);
        } finally {
            internalBusy = false;
        }
    }

    function handleKeydown(event: KeyboardEvent): void {
        if (event.key === 'Enter' && canPreview) {
            event.preventDefault();
            void submitPreview();
        }
    }
</script>

<div class="pl-gh-picker" data-github-source-picker>
    <div class="pl-gh-picker__row">
        <div class="pl-gh-picker__main">
            <Field
                label={t('plugins.page.github.source_label')}
                placeholder={t('plugins.page.github.source_placeholder')}
                help={t('plugins.page.github.source_help')}
                error={shownError ?? undefined}
                bind:value={source}
                disabled={isBusy}
                data-github-source
                onkeydown={handleKeydown}
            />
        </div>
        <div class="pl-gh-picker__act">
            <Button
                variant="secondary"
                disabled={!canPreview}
                data-github-preview
                onclick={() => void submitPreview()}
            >
                {t(isBusy ? 'plugins.page.github.previewing' : 'plugins.page.github.preview')}
            </Button>
        </div>
    </div>

    <Fold label={t('plugins.page.github.advanced')} bind:open={advancedOpen}>
        <div class="pl-gh-picker__advanced" data-github-advanced>
            <Field
                label={t('plugins.page.github.ref_label')}
                placeholder={t('plugins.page.github.ref_placeholder')}
                bind:value={ref}
                disabled={isBusy}
                data-github-ref
            />
            <Field
                label={t('plugins.page.github.subdir_label')}
                placeholder={t('plugins.page.github.subdir_placeholder')}
                bind:value={subdir}
                disabled={isBusy}
                data-github-subdir
            />
        </div>
    </Fold>
</div>

<style>
    @layer components {
        .pl-gh-picker {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
        }

        .pl-gh-picker__row {
            display: flex;
            align-items: flex-end;
            gap: var(--oc-space-2);
        }

        .pl-gh-picker__main {
            flex: 1 1 auto;
            min-width: 0;
        }

        .pl-gh-picker__act {
            flex: none;
        }

        .pl-gh-picker__advanced {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: var(--oc-space-2);
        }
    }
</style>
