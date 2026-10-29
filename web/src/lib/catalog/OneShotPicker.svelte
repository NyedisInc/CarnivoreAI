
<script lang="ts">
    import ModalShell from '../launchpad/ModalShell.svelte';
    import {
        SKILL_KEYS,
        isUnsupported,
        reasonOf,
        refusalMessage,
    } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import { refusalCodeOf } from './install-actions';
    import ConsentInstructions from './ConsentInstructions.svelte';
    import { oneShotReport, oneShotTargets, type OneShotReport } from './one-shot';

    interface Props {
        name: string;
        body: string | null;
        host: CatalogHost;
        t: Translate;
        writesInstructions?: boolean;
        instructionsDetails?: readonly string[];
        instructionsMore?: number;
        close: (value: null) => void;
    }

    const { name, body, host, t, close, writesInstructions = false, instructionsDetails = [], instructionsMore = 0 }: Props = $props();

    // svelte-ignore state_referenced_locally
    const targets = oneShotTargets(host.runningSessions());

    let sessionId = $state<string>(targets.length === 1 ? (targets[0]?.sessionId ?? '') : '');
    let busy = $state(false);
    let refusedCode = $state<string | null>(null);
    let unsupported = $state(false);
    let failure = $state<string | null>(null);
    let report = $state<OneShotReport | null>(null);

    const canPaste = $derived(!busy && !report && !!body && !!sessionId);

    async function paste(): Promise<void> {
        if (!canPaste || !body) return;
        busy = true;
        refusedCode = null;
        unsupported = false;
        failure = null;
        try {
            report = oneShotReport(await host.oneShot(sessionId, body));
        } catch (error) {
            if (isUnsupported(error)) {
                unsupported = true;
            } else {
                const code = refusalCodeOf(error);
                if (code) refusedCode = code;
                else failure = reasonOf(error, t);
            }
        } finally {
            busy = false;
        }
    }
</script>

<ModalShell
    title={t(SKILL_KEYS.oneShotTitle, { name })}
    dismissable={!busy}
    onCancel={() => close(null)}
>
    <div class="one-shot">
        <p class="one-shot__lead">{t(SKILL_KEYS.oneShotDetail)}</p>

        {#if writesInstructions}
            <ConsentInstructions {t} details={instructionsDetails} more={instructionsMore} />
        {/if}

        {#if !body}
            
            <p class="one-shot__note" role="status">{t(SKILL_KEYS.oneShotBodyAbsent)}</p>
        {:else if targets.length === 0}
            <p class="one-shot__note" role="status">{t(SKILL_KEYS.oneShotNone)}</p>
        {:else}
            <label class="one-shot__field">
                <span class="one-shot__label">{t(SKILL_KEYS.oneShotSession)}</span>
                <select
                    class="one-shot__select"
                    value={sessionId}
                    disabled={busy || !!report}
                    onchange={(event) => {
                        sessionId = (event.currentTarget as HTMLSelectElement).value;
                    }}
                >
                    <option value=""></option>
                    
                    {#each targets as target (target.sessionId)}
                        <option value={target.sessionId}>{target.label} ({target.agent})</option>
                    {/each}
                </select>
            </label>
        {/if}

        {#if unsupported}
            <p class="one-shot__refusal" role="alert">{t(SKILL_KEYS.refusedUnsupported)}</p>
        {/if}
        {#if refusedCode}
            <p class="one-shot__refusal" role="alert">{refusalMessage(refusedCode, t)}</p>
        {/if}
        {#if failure}
            <p class="one-shot__refusal" role="alert">{failure}</p>
        {/if}

        {#if report}
            
            <div class="one-shot__report" role="status">
                {#if report.pastedBytes !== null}
                    <p class="one-shot__line">
                        {t(SKILL_KEYS.oneShotPasted, { count: report.pastedBytes })}
                    </p>
                {/if}
                {#if report.strippedCount !== null && report.strippedCount > 0}
                    <p class="one-shot__line one-shot__line--out">
                        {t(SKILL_KEYS.oneShotStripped, { count: report.strippedCount })}
                    </p>
                {/if}
                {#if report.submitted === true}
                    <p class="one-shot__line">{t(SKILL_KEYS.oneShotSubmitted)}</p>
                {:else if report.submitted === false}
                    
                    <p class="one-shot__line one-shot__line--out">
                        {t(SKILL_KEYS.oneShotNotSubmitted)}
                    </p>
                {/if}
            </div>
        {/if}
    </div>

    {#snippet footer()}
        <button
            type="button"
            class="modal-btn"
            disabled={busy}
            onclick={() => close(null)}
        >{t(SKILL_KEYS.sheetCancel)}</button>
        {#if !report}
            <button
                type="button"
                class="modal-btn modal-btn-primary"
                disabled={!canPaste}
                onclick={() => void paste()}
            >{busy ? t(SKILL_KEYS.oneShotWorking) : t(SKILL_KEYS.oneShotConfirm)}</button>
        {/if}
    {/snippet}
</ModalShell>

<style>
    .one-shot {
        display: flex;
        flex-direction: column;
        gap: 10px;
        font-size: 12px;
    }

    .one-shot__lead {
        margin: 0;
        color: var(--oc-text-primary);
        line-height: 1.45;
    }

    .one-shot__note {
        margin: 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-yellow);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        line-height: 1.45;
    }

    .one-shot__field {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .one-shot__label {
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .one-shot__select {
        padding: 6px 8px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 3px;
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-family: inherit;
        font-size: 12px;
    }

    .one-shot__refusal {
        margin: 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-coral);
        background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-raised));
        color: var(--oc-text-primary);
        line-height: 1.45;
    }

    .one-shot__report {
        display: flex;
        flex-direction: column;
        gap: 3px;
        padding: 6px 8px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 4px;
    }

    .one-shot__line {
        margin: 0;
        color: var(--oc-text-primary);
        line-height: 1.45;
    }

    .one-shot__line--out {
        color: var(--oc-yellow);
    }


    @media (max-width: 767px) {
        .modal-btn {
            min-height: 44px;
        }

        .one-shot__select {
            min-height: 44px;
        }
    }
</style>
