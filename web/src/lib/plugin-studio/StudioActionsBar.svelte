<script lang="ts">
    import { Button, Field, Segmented, Tag } from '../base';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import type {
        InstallWorkspaceResult,
        PublishMode,
        PublishWorkspaceRequest,
        PublishWorkspaceResult,
        SandboxTestReport,
        StudioBusyAction,
    } from './types';
    import './plugin-studio.css';

    interface Props {
        busyAction: StudioBusyAction;
        sandboxResult: SandboxTestReport | null;
        installResult: InstallWorkspaceResult | null;
        publishPreview: PublishWorkspaceResult | null;
        publishResult: PublishWorkspaceResult | null;
        onTestSandbox: () => Promise<unknown>;
        onInstall: () => Promise<unknown>;
        onPublish: (req: PublishWorkspaceRequest) => Promise<unknown>;
        onResetPublish: () => void;
        t?: Translate;
    }

    const {
        busyAction,
        sandboxResult,
        installResult,
        publishPreview,
        publishResult,
        onTestSandbox,
        onInstall,
        onPublish,
        onResetPublish,
        t = appT,
    }: Props = $props();

    let publishOpen = $state(false);
    let publishMode = $state<PublishMode>('local');
    let repo = $state('');
    let tag = $state('');
    let subdir = $state('');
    let commitSha = $state('');

    const busy = $derived(busyAction !== null);
    const canConfirmPublish = $derived(
        Boolean(publishPreview?.ok && publishPreview?.dry_run && publishPreview?.preview?.can_send !== false),
    );
    const previewBlocked = $derived(
        Boolean(publishPreview && (!publishPreview.ok || publishPreview.preview?.can_send === false)),
    );
    const previewRefusals = $derived.by(() => {
        const raw = publishPreview?.preview?.refusals;
        if (!Array.isArray(raw)) return [] as Array<Record<string, unknown>>;
        return raw.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object');
    });

    function currentPublishPayload(dryRun: boolean): PublishWorkspaceRequest {
        const previewDigestValue =
            !dryRun && typeof publishPreview?.preview?.digest === 'string' && publishPreview.preview.digest.trim()
                ? publishPreview.preview.digest.trim()
                : undefined;
        if (publishMode === 'github') {
            const cleanRepo = repo.trim();
            const cleanTag = tag.trim();
            const pointer = cleanRepo && cleanTag ? `${cleanRepo}@${cleanTag}` : null;
            return {
                mode: 'github',
                repo: cleanRepo || null,
                tag: cleanTag || null,
                pointer,
                subdir: subdir.trim() || null,
                commit_sha: commitSha.trim() || null,
                ...(previewDigestValue ? { digest: previewDigestValue } : {}),
                dry_run: dryRun,
            };
        }
        return {
            mode: 'local',
            ...(previewDigestValue ? { digest: previewDigestValue } : {}),
            dry_run: dryRun,
        };
    }

    function handleModeChange(next: string): void {
        publishMode = next === 'github' ? 'github' : 'local';
        onResetPublish();
    }

    function invalidateDryRun(): void {
        if (publishPreview || publishResult) {
            onResetPublish();
        }
    }

    const previewDigest = $derived.by(() => {
        const raw = publishPreview?.preview?.digest;
        return typeof raw === 'string' && raw ? raw.slice(0, 12) : 'ok';
    });
</script>

<div class="ps-actions-bar" data-studio-actions>
    <div class="ps-actions-bar__group">
        <Button
            variant="secondary"
            disabled={busy}
            data-studio-sandbox
            onclick={() => void onTestSandbox()}
        >
            {busyAction === 'sandbox'
                ? t('plugin_studio.actions.testing')
                : t('plugin_studio.actions.test_sandbox')}
        </Button>

        <Button
            variant="confirm"
            disabled={busy}
            data-studio-install
            onclick={() => void onInstall()}
        >
            {busyAction === 'install'
                ? t('plugin_studio.actions.installing')
                : t('plugin_studio.actions.install')}
        </Button>

        <Button
            variant="secondary"
            disabled={busy}
            data-studio-publish-toggle
            onclick={() => {
                publishOpen = !publishOpen;
                if (!publishOpen) onResetPublish();
            }}
        >
            {t('plugin_studio.actions.publish')}
        </Button>
    </div>

    <div class="ps-actions-bar__group">
        {#if sandboxResult}
            <Tag tone={sandboxResult.ok ? 'ok' : 'danger'}>
                {sandboxResult.ok
                    ? t('plugin_studio.actions.sandbox_pass')
                    : t('plugin_studio.actions.sandbox_fail')}
            </Tag>
        {/if}
        {#if installResult?.ok}
            <Tag tone="ok">
                {t('plugin_studio.actions.installed_ok', { id: installResult.plugin_id })}
            </Tag>
        {/if}
        {#if publishResult?.ok}
            <Tag tone="ok">{t('plugin_studio.publish.submitted')}</Tag>
        {/if}
    </div>
</div>

{#if sandboxResult && (sandboxResult.errors.length > 0 || sandboxResult.warnings.length > 0 || sandboxResult.unit?.output)}
    <div class="ps-check-row" data-studio-sandbox-output>
        {#if sandboxResult.errors.length > 0}
            <ul class="ps-findings">
                {#each sandboxResult.errors as err, idx (`sb-err-${idx}`)}
                    <li>{err}</li>
                {/each}
            </ul>
        {/if}
        {#if sandboxResult.warnings.length > 0}
            <ul class="ps-findings">
                {#each sandboxResult.warnings as warn, idx (`sb-warn-${idx}`)}
                    <li>{warn}</li>
                {/each}
            </ul>
        {/if}
        {#if sandboxResult.unit?.output}
            <pre class="ps-pre">{sandboxResult.unit.output}</pre>
        {/if}
    </div>
{/if}

{#if publishOpen}
    <div class="ps-publish-panel" data-studio-publish-panel>
        <div class="ps-pane__bar">
            <h3 class="ps-pane__heading">{t('plugin_studio.publish.heading')}</h3>
            <Segmented
                label={t('plugin_studio.publish.mode_label')}
                value={publishMode}
                options={[
                    { value: 'local', label: t('plugin_studio.publish.mode_local') },
                    { value: 'github', label: t('plugin_studio.publish.mode_github') },
                ]}
                onchange={handleModeChange}
            />
        </div>

        {#if publishMode === 'github'}
            <div class="ps-publish-panel__grid">
                <Field
                    label={t('plugin_studio.publish.repo')}
                    placeholder={t('plugin_studio.publish.repo_placeholder')}
                    bind:value={repo}
                    oninput={invalidateDryRun}
                    data-studio-publish-repo
                />
                <Field
                    label={t('plugin_studio.publish.tag')}
                    placeholder={t('plugin_studio.publish.tag_placeholder')}
                    bind:value={tag}
                    oninput={invalidateDryRun}
                    data-studio-publish-tag
                />
                <Field
                    label={t('plugin_studio.publish.subdir')}
                    bind:value={subdir}
                    oninput={invalidateDryRun}
                    data-studio-publish-subdir
                />
                <Field
                    label={t('plugin_studio.publish.commit_sha')}
                    bind:value={commitSha}
                    oninput={invalidateDryRun}
                    data-studio-publish-sha
                />
            </div>
        {/if}

        <div class="ps-actions-bar__group">
            <Button
                variant="secondary"
                disabled={busy}
                data-studio-publish-dryrun
                onclick={() => void onPublish(currentPublishPayload(true))}
            >
                {busyAction === 'publish' && !canConfirmPublish
                    ? t('plugin_studio.publish.previewing')
                    : t('plugin_studio.publish.preview_btn')}
            </Button>

            {#if publishPreview}
                <Button
                    variant="confirm"
                    disabled={busy || !canConfirmPublish}
                    data-studio-publish-confirm
                    onclick={() => void onPublish(currentPublishPayload(false))}
                >
                    {busyAction === 'publish'
                        ? t('plugin_studio.publish.submitting')
                        : t('plugin_studio.publish.confirm_btn')}
                </Button>
            {/if}

            <Button
                variant="quiet"
                disabled={busy}
                onclick={() => {
                    publishOpen = false;
                    onResetPublish();
                }}
            >
                {t('plugin_studio.publish.cancel')}
            </Button>

            {#if publishPreview}
                <Tag tone={canConfirmPublish ? 'ok' : 'danger'}>
                    {canConfirmPublish
                        ? t('plugin_studio.publish.preview_ok', { digest: previewDigest })
                        : t('plugin_studio.publish.preview_blocked')}
                </Tag>
            {/if}
        </div>

        {#if previewBlocked}
            <div class="ps-banner" role="alert" data-studio-publish-blocked>
                <p class="ps-banner__title">{t('plugin_studio.publish.blocked_heading')}</p>
                <p class="ps-banner__detail">{t('plugin_studio.publish.blocked_hint')}</p>
                {#if previewRefusals.length > 0}
                    <ul class="ps-findings" data-studio-publish-refusals>
                        {#each previewRefusals as refusal, idx (`pub-refusal-${idx}`)}
                            <li>
                                {String(refusal.code ?? '')}{refusal.path ? ` (${String(refusal.path)})` : ''}{refusal.detail || refusal.reason ? `: ${String(refusal.detail ?? refusal.reason)}` : ''}
                            </li>
                        {/each}
                    </ul>
                {/if}
            </div>
        {/if}

        {#if publishPreview?.preview || publishResult?.submission}
            <pre class="ps-pre">{JSON.stringify(publishResult?.submission ?? publishPreview?.preview, null, 2)}</pre>
        {/if}
    </div>
{/if}
