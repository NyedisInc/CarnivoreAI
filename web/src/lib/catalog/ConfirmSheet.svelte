<!-- the detail pane -->
<script lang="ts">
    import Fold from '../base/Fold.svelte';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import CplugFacts from './CplugFacts.svelte';
    import FlaggedWarningBox from './FlaggedWarningBox.svelte';
    import PermissionDiffPanel from './PermissionDiffPanel.svelte';
    import {
        hasPermissionDiffChanges,
        isProvenanceBlocked,
        type FlaggedWarningMeta,
        type PermissionDiffData,
    } from './permission-diff';
    import type { UpdateSummaryProps } from './installed-actions';
    import UpdateDiffView from './UpdateDiffView.svelte';
    import UpdateSummary from './UpdateSummary.svelte';
    import type { CplugFactsData, UpdateDiff } from './types';
    import { hasCplugCapabilities } from './update-notes';
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';

    interface Props {
        title: string;
        lead: string;
        linesHeading?: string | null;
        lines?: readonly string[];
        confirmLabel: string;
        busyLabel: string;
        busy?: boolean;
        destructive?: boolean;
        document?: string | null;
        tickLabel?: string | null;
        diff?: UpdateDiff | null;
        cplugFacts?: CplugFactsData | null;
        permissionDiff?: PermissionDiffData | null;
        flaggedWarning?: FlaggedWarningMeta | null;
        isPluginUpdate?: boolean;
        updateSummary?: UpdateSummaryProps | null;
        /* could not be read */
        documentMissing?: string | null;
        t: Translate;
        close: (value: boolean | null) => void;
    }

    const {
        title,
        lead,
        linesHeading = null,
        lines = [],
        confirmLabel,
        busyLabel,
        busy = false,
        destructive = false,
        document: body = null,
        tickLabel = null,
        documentMissing = null,
        diff = null,
        cplugFacts = undefined,
        permissionDiff = null,
        flaggedWarning = null,
        isPluginUpdate = false,
        updateSummary = null,
        t,
        close,
    }: Props = $props();

    let accepted = $state(false);
    let permAccepted = $state(false);
    let flaggedAccepted = $state(false);
    let technicalOpen = $state(false);

    const provenanceBlocked = $derived(isProvenanceBlocked(permissionDiff));
    const showPermDiff = $derived(hasPermissionDiffChanges(permissionDiff));
    const needsPermAck = $derived(Boolean(showPermDiff && permissionDiff?.requiresReconsent && !provenanceBlocked));
    const needsFlaggedAck = $derived(Boolean(flaggedWarning?.requiresWarningAck));
    const showCplugFacts = $derived(
        cplugFacts !== undefined &&
            (!isPluginUpdate || (hasCplugCapabilities(cplugFacts) && (showPermDiff || cplugFacts === null))),
    );
    const hasTechnicalDetails = $derived(Boolean(isPluginUpdate && (body || (diff && diff.changes.length > 0))));

    const canConfirm = $derived(
        !busy &&
            !provenanceBlocked &&
            (!needsPermAck || permAccepted) &&
            (!needsFlaggedAck || flaggedAccepted) &&
            (showCplugFacts ? !!body && !!cplugFacts && accepted : !tickLabel || (!!body && accepted)),
    );
</script>

<ModalShell
    {title}
    width={isPluginUpdate || flaggedWarning || showCplugFacts || showPermDiff ? 'min(560px, 92vw)' : undefined}
    dismissable={!busy}
    onCancel={() => close(null)}
>
    <div class="confirm">
        {#if isPluginUpdate && updateSummary}
            <UpdateSummary
                fromVersion={updateSummary.fromVersion}
                toVersion={updateSummary.toVersion}
                notes={updateSummary.notes}
                screenshots={updateSummary.screenshots}
                noPermissions={updateSummary.noPermissions}
                noTools={updateSummary.noTools}
                permissionsUnchanged={updateSummary.permissionsUnchanged}
                {t}
            />
        {:else}
            <p class="confirm__lead">{lead}</p>
        {/if}
        {#if !isPluginUpdate}
            {#if body}
                <p class="confirm__heading">{t(SKILL_KEYS.sheetBodyHeading)}</p>
                <p class="confirm__size">{t(SKILL_KEYS.sheetBodySize, { count: body.length })}</p>
                <pre class="confirm__document">{body}</pre>
            {:else if documentMissing}
                
                <p class="confirm__missing" role="status">{documentMissing}</p>
            {/if}
            {#if diff}
                <UpdateDiffView {diff} permissionDiff={null} {t} />
            {/if}
        {/if}
        {#if showPermDiff && permissionDiff}
            <PermissionDiffPanel
                diff={permissionDiff}
                bind:accepted={permAccepted}
                {busy}
                showAck={permissionDiff.requiresReconsent}
                {t}
            />
        {/if}
        {#if flaggedWarning && (flaggedWarning.flagged || flaggedWarning.requiresWarningAck)}
            <FlaggedWarningBox
                summary={flaggedWarning.summary}
                warningReasons={flaggedWarning.warningReasons}
                warnings={flaggedWarning.warnings}
                bind:accepted={flaggedAccepted}
                {busy}
                requireAck={flaggedWarning.requiresWarningAck}
                {t}
            />
        {/if}
        
        {#if linesHeading}
            <p class="confirm__heading">{linesHeading}</p>
        {/if}
        {#if lines.length}
            
            <ul class="confirm__lines">
                {#each lines as line}
                    <li class="confirm__line">{line}</li>
                {/each}
            </ul>
        {/if}
        {#if showCplugFacts}
            <CplugFacts
                facts={cplugFacts ?? null}
                {accepted}
                {busy}
                isUpdate={isPluginUpdate}
                {t}
                onAccept={(next) => { accepted = next; }}
            />
        {/if}
        {#if hasTechnicalDetails}
            <div class="confirm__technical" data-update-technical-fold>
                <Fold
                    label={t(SKILL_KEYS.updateTechnicalFold)}
                    count={diff?.changes.length || undefined}
                    bind:open={technicalOpen}
                >
                    <div class="confirm__technical-body">
                        {#if diff}
                            <UpdateDiffView {diff} permissionDiff={null} {t} />
                        {/if}
                        {#if body}
                            <p class="confirm__heading">{t(SKILL_KEYS.sheetBodyHeading)}</p>
                            <pre class="confirm__document">{body}</pre>
                        {/if}
                    </div>
                </Fold>
            </div>
        {/if}
        {#if tickLabel}
            <label class="confirm__accept">
                <input
                    type="checkbox"
                    checked={accepted}
                    disabled={busy || !body}
                    onchange={(event) => {
                        accepted = (event.currentTarget as HTMLInputElement).checked;
                    }}
                />
                <span>{tickLabel}</span>
            </label>
        {/if}
    </div>
    {#snippet footer()}
        <button
            type="button"
            class="modal-btn"
            disabled={busy}
            onclick={() => close(null)}
        >{t(SKILL_KEYS.sheetCancel)}</button>
        <button
            type="button"
            class="modal-btn modal-btn-primary"
            class:confirm__danger={destructive}
            disabled={!canConfirm}
            onclick={() => close(true)}
        >{busy ? busyLabel : confirmLabel}</button>
    {/snippet}
</ModalShell>

<style>
    .confirm {
        display: flex;
        flex-direction: column;
        gap: 8px;
        font-size: 12px;
    }

    .confirm__lead {
        margin: 0;
        color: var(--oc-text-primary);
        line-height: 1.45;
    }

    .confirm__heading {
        margin: 0;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .confirm__lines {
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .confirm__line {
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.5;
        overflow-wrap: anywhere;
    }

    .confirm__size {
        margin: -4px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }

    .confirm__document {
        max-height: 220px;
        overflow: auto;
        margin: 0;
        padding: 8px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 4px;
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.45;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }

    .confirm__missing {
        margin: 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-yellow);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        line-height: 1.45;
    }

    .confirm__accept {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        color: var(--oc-text-primary);
        line-height: 1.45;
        cursor: pointer;
    }

    .confirm__accept input {
        margin-top: 2px;
        flex-shrink: 0;
        width: 16px;
        height: 16px;
    }

    @media (max-width: 767px) {
        .confirm__document {
            max-height: 40vh;
        }

        .modal-btn {
            min-height: 44px;
        }

        .confirm__accept {
            min-height: 44px;
            align-items: center;
        }

        .confirm__accept input {
            margin-top: 0;
            width: 22px;
            height: 22px;
        }
    }

    .confirm__danger {
        border-color: var(--oc-coral);
        color: var(--oc-coral);
    }

    .confirm__technical {
        border-top: var(--oc-border) solid var(--oc-line-faint);
        padding-top: var(--oc-space-1-5);
    }

    .confirm__technical-body {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        padding-top: var(--oc-space-1-5);
    }
</style>
