<!-- already running -->
<script lang="ts">
    import ModalShell from '../launchpad/ModalShell.svelte';
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import { SKILL_KEYS, reasonOf } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import { tryPrompt } from './try-it';
    import ConsentInstructions from './ConsentInstructions.svelte';

    interface Props {
        name: string;
        body: string | null;
        files: number | null;
        host: CatalogHost;
        t: Translate;
        writesInstructions?: boolean;
        instructionsDetails?: readonly string[];
        instructionsMore?: number;
        close: (value: 'paste' | null) => void;
    }

    const { name, body, files, host, t, close, writesInstructions = false, instructionsDetails = [], instructionsMore = 0 }: Props = $props();

    let task = $state('');
    let busy = $state(false);
    let started = $state(false);
    let failure = $state<string | null>(null);

    const built = $derived(tryPrompt(body, task, t));
    const canRun = $derived(!busy && !started && !!built.prompt);

    async function run(): Promise<void> {
        if (!canRun || !built.prompt) return;
        busy = true;
        failure = null;
        try {
            await host.tryInScratch(built.prompt);
            started = true;
        } catch (error) {
            failure = t(BROWSE_KEYS.tryFailed, { reason: reasonOf(error, t) });
        } finally {
            busy = false;
        }
    }
</script>

<ModalShell
    title={t(BROWSE_KEYS.tryTitle, { name })}
    dismissable={!busy}
    onCancel={() => close(null)}
>
    <div class="cat-try">
        <p class="cat-try__lead">{t(BROWSE_KEYS.tryLead)}</p>

        {#if writesInstructions}
            <ConsentInstructions {t} details={instructionsDetails} more={instructionsMore} />
        {/if}

        {#if files !== null && files > 1}
            <p class="cat-try__note" role="status">{t(BROWSE_KEYS.tryManyFiles, { count: files })}</p>
        {/if}

        {#if !body && !built.tooLarge}
            <p class="cat-try__note" role="status">{t(BROWSE_KEYS.tryBodyAbsent)}</p>
        {:else if built.tooLarge}
            <p class="cat-try__refusal" role="alert">{t(BROWSE_KEYS.tryTooLarge)}</p>
        {/if}

        <label class="cat-try__field">
            <span class="cat-try__label">{t(BROWSE_KEYS.tryTask)}</span>
            <input
                class="cat-try__input"
                type="text"
                maxlength="300"
                placeholder={t(BROWSE_KEYS.tryTaskHint)}
                bind:value={task}
                disabled={busy || started}
            />
        </label>

        {#if failure}
            <p class="cat-try__refusal" role="alert">{failure}</p>
        {/if}
        {#if started}
            <p class="cat-try__note" role="status">{t(BROWSE_KEYS.tryStarted)}</p>
        {/if}
    </div>

    {#snippet footer()}
        <button
            type="button"
            class="modal-btn modal-btn-secondary"
            disabled={busy}
            onclick={() => close('paste')}
        >
            {t(BROWSE_KEYS.tryIntoSession)}
        </button>
        <button
            type="button"
            class="modal-btn modal-btn-secondary"
            disabled={busy}
            onclick={() => close(null)}
        >
            {t(SKILL_KEYS.sheetCancel)}
        </button>
        {#if !started}
            <button
                type="button"
                class="modal-btn modal-btn-primary"
                disabled={!canRun}
                onclick={() => void run()}
            >{busy ? t(BROWSE_KEYS.tryRunning) : t(BROWSE_KEYS.tryRun)}</button>
        {/if}
    {/snippet}
</ModalShell>

<style>
    .cat-try {
        display: flex;
        flex-direction: column;
        gap: 10px;
        font-size: 12px;
    }

    .cat-try__lead {
        margin: 0;
        color: var(--oc-text-primary);
        line-height: 1.45;
    }

    .cat-try__note {
        margin: 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-yellow);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        line-height: 1.45;
    }

    .cat-try__field {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .cat-try__label {
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-try__input {
        padding: 6px 8px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 3px;
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-family: inherit;
        font-size: 12px;
    }

    .cat-try__refusal {
        margin: 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-coral);
        background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-raised));
        color: var(--oc-text-primary);
        line-height: 1.45;
    }

    @media (max-width: 767px) {
        .modal-btn,
        .cat-try__input {
            min-height: 44px;
        }
    }
</style>
