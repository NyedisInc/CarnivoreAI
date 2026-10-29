<!-- already running the detail pane -->
<script lang="ts">
    import ModalShell from '../launchpad/ModalShell.svelte';
    import UpdateDiffView from './UpdateDiffView.svelte';
    import type { UpdateDiff } from './types';
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
        t,
        close,
    }: Props = $props();

    let accepted = $state(false);

    /* could not be read */
    const canConfirm = $derived(!busy && (!tickLabel || (!!body && accepted)));
</script>

<ModalShell {title} dismissable={!busy} onCancel={() => close(null)}>
    <div class="confirm">
        <p class="confirm__lead">{lead}</p>
        {#if body}
            <p class="confirm__heading">{t(SKILL_KEYS.sheetBodyHeading)}</p>
            <p class="confirm__size">{t(SKILL_KEYS.sheetBodySize, { count: body.length })}</p>
            <pre class="confirm__document">{body}</pre>
        {:else if documentMissing}
            
            <p class="confirm__missing" role="status">{documentMissing}</p>
        {/if}
        {#if diff}
            <UpdateDiffView {diff} {t} />
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
</style>
