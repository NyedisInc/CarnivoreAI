<!-- could not be read -->
<script lang="ts">
    import { onMount } from 'svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import PreviewFacts from './InstallPreview.svelte';
    import InstallChoices from './InstallChoices.svelte';
    import { SKILL_KEYS, reasonOf, refusalMessage } from '../../../../client/js/labels/skill.js';
    import type { ProjectRow, Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import type { CardView } from './card';
    import { refusalCodeOf, refusalPayloadOf } from './install-actions';
    import { consentBlock, needsScriptConsent, scriptFiles } from './scripts';
    import ConsentScripts from './ConsentScripts.svelte';
    import ConsentInstructions from './ConsentInstructions.svelte';
    import { MAX_INSTRUCTIONS_DETAILS, reviewView } from './review';
    import { themeFacts } from './theme-swatch';
    import PluginFacts from './PluginFacts.svelte';
    import { mcpServers } from './mcp';
    import ModFacts from './ModFacts.svelte';
    import CplugFacts from './CplugFacts.svelte';
    import { pluginFacts } from './plugin-facts';
    import LoadoutMembers from './LoadoutMembers.svelte';
    import { loadoutFacts } from './loadout-facts';
    import { KIND_KEYS } from '../../../../client/js/labels/catalog-kind.js';
    import type { InstallPreview, InstallRequest, InstallScope, SheetOutcome } from './types';

    interface Props {
        card: CardView;
        host: CatalogHost;
        t: Translate;
        close: (value: SheetOutcome | null) => void;
        prefill?: { scope: InstallScope; projectPath: string | null } | null;
    }

    const { card, host, t, close, prefill = null }: Props = $props();

    let scope = $state<InstallScope>(prefill?.scope ?? 'global');
    let projects = $state<ProjectRow[]>([]);
    let projectPath = $state<string | null>(prefill?.projectPath ?? null);
    let preview = $state<InstallPreview | null>(null);
    let choices = $state<InstallPreview['choices']>(null);
    let choice = $state<string | null>(null);
    let refusedCode = $state<string | null>(null);
    let failure = $state<string | null>(null);
    let busy = $state(false);
    let scriptsAccepted = $state(false);
    let modTrust = $state(false);
    let modFlagged = $state(false);
    let cplugAccepted = $state(false);
    let advancedOpen = $state(false);

    function request(consented = false): InstallRequest {
        const body: InstallRequest = { item_id: card.id || '', scope };
        if (scope === 'project') body.project_path = projectPath;
        if (choice) body.choice = choice;
        if (consented && preview?.plan_token) body.plan_token = preview.plan_token;
        if (consented && scriptsAccepted) {
            const block = consentBlock(preview);
            if (block) body.consent = block;
        }
        if (consented && card.isMod && modReady) {
            body.consent = {
                ...consentBlock(preview)!,
                mod_trust: true,
                mod_flagged_ack: modFlagged,
                mod_report_sha: preview!.mod_report_sha!,
            };
        }
        if (consented && card.isCplug && cplugReady) {
            body.consent = {
                ...consentBlock(preview)!,
                cplug_accepted: true,
                cplug_facts_sha: preview!.cplug_facts_sha!,
            };
        }
        return body;
    }

    const scripts = $derived(scriptFiles(preview));
    const consentRequired = $derived(needsScriptConsent(preview) && !card.isMod && !card.isCplug);
    const modFlaggedNeeded = $derived(preview?.mod_flagged_ack_needed !== false);
    const modReady = $derived(
        card.isMod &&
            !!preview?.mod_report_sha &&
            !!preview?.mod_report &&
            consentBlock(preview) !== null &&
            modTrust &&
            (!modFlaggedNeeded || modFlagged),
    );

    const cplugReady = $derived(
        card.isCplug &&
            !!preview?.cplug_facts_sha &&
            !!preview?.cplug_facts &&
            consentBlock(preview) !== null &&
            cplugAccepted,
    );

    const consentExpressible = $derived(consentBlock(preview) !== null);

    const facts = $derived(card.isTheme ? themeFacts(preview?.body ?? null) : null);

    const plugin = $derived(
        card.isPlugin
            ? pluginFacts(preview?.body ?? null, preview?.files ?? null)
            : null,
    );

    const loadout = $derived(
        card.isLoadout
            ? loadoutFacts(preview?.body ?? null, preview?.loadout_members ?? null)
            : null,
    );

    const membersNeedConsent = $derived(loadout !== null && loadout.anyScripts);

    const writesInstructions = $derived(
        reviewView(preview?.review).writesInstructions || (loadout?.anyInstructions ?? false),
    );
    const instructionsDetails = $derived(
        [...reviewView(preview?.review).instructionsDetails, ...(loadout?.instructionsDetails ?? [])].slice(
            0,
            MAX_INSTRUCTIONS_DETAILS,
        ),
    );
    const instructionsMore = $derived(
        reviewView(preview?.review).instructionsMore +
            (loadout?.instructionsMore ?? 0) +
            (reviewView(preview?.review).instructionsDetails.length +
                (loadout?.instructionsDetails.length ?? 0) -
                instructionsDetails.length),
    );

    const scopeReady = $derived(scope === 'global' || !!projectPath);

    const canConfirm = $derived(
        !busy &&
            !!preview &&
            !refusedCode &&
            scopeReady &&
            (!choices || !!choice) &&
            (!consentRequired || (scriptsAccepted && consentExpressible)) &&
            (!card.isMod || modReady) &&
            (!card.isCplug || cplugReady),
    );

    async function runPreview(): Promise<void> {
        if (!scopeReady) return;
        busy = true;
        refusedCode = null;
        failure = null;
        choices = null;
        choice = null;
        scriptsAccepted = false;
        modTrust = false;
        modFlagged = false;
        cplugAccepted = false;
        try {
            preview = await host.previewInstall(request());
        } catch (error) {
            const code = refusalCodeOf(error);
            const body = refusalPayloadOf(error) as InstallPreview | null;
            if (code === 'name_taken' && body) {
                preview = body;
                choices = body.choices ?? null;
                refusedCode = choices && choices.length ? null : code;
            } else if (code) {
                preview = null;
                refusedCode = code;
            } else {
                preview = null;
                failure = reasonOf(error, t);
            }
        } finally {
            busy = false;
        }
    }

    function onScopeChange(next: InstallScope): void {
        scope = next;
        void runPreview();
    }

    function onProjectChange(event: Event): void {
        const target = event.currentTarget as HTMLSelectElement;
        projectPath = target.value || null;
        void runPreview();
    }

    async function confirm(): Promise<void> {
        if (!canConfirm) return;
        busy = true;
        failure = null;
        try {
            const row = await host.install(request(true));
            close({ outcome: 'installed', row });
        } catch (error) {
            const code = refusalCodeOf(error);
            if (code) {
                refusedCode = code;
            } else {
                failure = reasonOf(error, t);
            }
        } finally {
            busy = false;
        }
    }

    function cancel(): void {
        close(refusedCode ? { outcome: 'refused', code: refusedCode } : null);
    }

    onMount(() => {
        // could not be read
        void (async () => {
            try {
                projects = await host.listProjects();
            } catch (error) {
                console.error('CloudeWeb: the install sheet could not list projects', error);
            }
            try {
                const seed = await host.currentProjectPath();
                if (!prefill?.projectPath) projectPath = seed;
            } catch (error) {
                console.error('CloudeWeb: the install sheet could not read the current project', error);
            }
        })();
        void runPreview();
    });
</script>

<ModalShell
    title={t(SKILL_KEYS.sheetTitle, { name: card.headline || card.id || '' })}
    dismissable={!busy}
    onCancel={cancel}
>
    
    <div class="cat sheet">
        
        {#if !card.isTheme}
        <fieldset class="sheet__scope">
            <legend class="sheet__legend">{t(SKILL_KEYS.sheetScopeLegend)}</legend>
            {#if card.isCplug}
                
                <p class="sheet__note">{t(KIND_KEYS.cplugScopeGlobalOnly)}</p>
            {:else if card.isMod}
                
                <p class="sheet__note">{t(KIND_KEYS.modScopeGlobalOnly)}</p>
            {:else}
            {#if card.isPlugin}
                
                <p class="sheet__note">{t(KIND_KEYS.pluginScopeNote)}</p>
                <p class="sheet__note">{t(KIND_KEYS.pluginScopeProjectTrust)}</p>
            {/if}
            <label class="sheet__radio">
                <input
                    type="radio"
                    name="catalog-scope"
                    value="global"
                    checked={scope === 'global'}
                    onchange={() => onScopeChange('global')}
                />
                <span class="sheet__radio-label">{t(SKILL_KEYS.sheetScopeGlobal)}</span>
                <span class="sheet__radio-detail">{t(SKILL_KEYS.sheetScopeGlobalDetail)}</span>
            </label>
            <label class="sheet__radio">
                <input
                    type="radio"
                    name="catalog-scope"
                    value="project"
                    checked={scope === 'project'}
                    disabled={projects.length === 0}
                    onchange={() => onScopeChange('project')}
                />
                <span class="sheet__radio-label">{t(SKILL_KEYS.sheetScopeProject)}</span>
                <span class="sheet__radio-detail">{t(SKILL_KEYS.sheetScopeProjectDetail)}</span>
            </label>
            {#if projects.length === 0}
                <p class="sheet__note">{t(SKILL_KEYS.sheetProjectNone)}</p>
            {:else if scope === 'project'}
                <label class="sheet__field">
                    <span class="sheet__field-label">{t(SKILL_KEYS.sheetProjectLabel)}</span>
                    <select class="sheet__select" value={projectPath ?? ''} onchange={onProjectChange}>
                        <option value=""></option>
                        {#each projects as project (project.path || project.name)}
                            <option value={project.path ?? ''}>{project.name || project.path}</option>
                        {/each}
                    </select>
                </label>
            {/if}
            {/if}
        </fieldset>
        {/if}

        {#if busy && !preview}
            <p class="sheet__note">{t(SKILL_KEYS.sheetPreviewLoading)}</p>
        {/if}

        {#if failure}
            <p class="sheet__refusal" role="alert">
                {t(SKILL_KEYS.sheetPreviewUnavailable, { reason: failure })}
            </p>
        {/if}

        {#if refusedCode}
            <p class="sheet__refusal" role="alert">{refusalMessage(refusedCode, t)}</p>
        {/if}

        {#if choices && choices.length}
            <InstallChoices
                {t}
                choices={choices ?? []}
                name={card.name || card.headline || ''}
                selected={choice}
                onChoose={(picked) => { choice = picked; }}
            />
        {/if}

        {#if preview}
            
            {#if consentRequired}
                <p class="sheet__scripts-lead" role="status">
                    {t(SKILL_KEYS.consentReadFirst)}
                </p>
            {/if}

            <PreviewFacts {preview} kind={card.kind} {t} part={card.isTheme ? 'facts' : 'all'} />

            {#if plugin}
                <PluginFacts facts={plugin} {t} mcp={mcpServers(preview)} />
            {/if}

            {#if card.isMod}
                <ModFacts
                    report={preview.mod_report ?? null}
                    flaggedNeeded={modFlaggedNeeded}
                    groups={preview.mod_settings_groups ?? []}
                    trust={modTrust}
                    flagged={modFlagged}
                    {busy}
                    {t}
                    onTrust={(next) => { modTrust = next; }}
                    onFlagged={(next) => { modFlagged = next; }}
                />
            {/if}

            {#if card.isCplug}
                <CplugFacts
                    facts={preview.cplug_facts ?? null}
                    accepted={cplugAccepted}
                    {busy}
                    {t}
                    onAccept={(next) => { cplugAccepted = next; }}
                />
            {/if}

            {#if loadout}
                
                <LoadoutMembers facts={loadout} {t} />
                {#if membersNeedConsent}
                    <p class="sheet__note" role="note">
                        {t(KIND_KEYS.loadoutMemberScripts)}
                    </p>
                {/if}
            {/if}

            {#if writesInstructions}
                <ConsentInstructions {t} details={instructionsDetails} more={instructionsMore} />
            {/if}

            {#if consentRequired}
                <ConsentScripts
                    {scripts}
                    {t}
                    accepted={scriptsAccepted}
                    expressible={consentExpressible}
                    {busy}
                    onAccept={(next) => { scriptsAccepted = next; }}
                />
            {/if}
            {#if card.isTheme}
                
                <button
                    type="button"
                    class="sheet__advanced"
                    aria-expanded={advancedOpen}
                    aria-controls="sheet-advanced"
                    onclick={() => (advancedOpen = !advancedOpen)}
                >{t(SKILL_KEYS.sheetAdvanced)}</button>
                {#if advancedOpen}
                    <div id="sheet-advanced" class="sheet__advanced-body">
                        <PreviewFacts {preview} kind={card.kind} {t} part="advanced" />
                        {#if facts?.effects}
                            <div class="sheet__theme-effects" role="note">
                                <p class="sheet__heading">{t(KIND_KEYS.themeEffectsHeading)}</p>
                                <p class="sheet__note">
                                    {t(KIND_KEYS.themeEffectsFile, { name: facts.effects })}
                                </p>
                                <p class="sheet__note">{t(KIND_KEYS.themeEffectsDetail)}</p>
                            </div>
                        {/if}
                    </div>
                {/if}
            {/if}
        {/if}
    </div>

    {#snippet footer()}
        <button type="button" class="modal-btn" onclick={cancel}>{t(SKILL_KEYS.sheetCancel)}</button>
        <button
            type="button"
            class="modal-btn modal-btn-primary"
            disabled={!canConfirm}
            onclick={confirm}
        >{busy
            ? t(SKILL_KEYS.stateInstalling)
            : consentRequired || card.isMod || card.isCplug
              ? t(SKILL_KEYS.consentConfirm)
              : t(SKILL_KEYS.sheetConfirm)}</button>
    {/snippet}
</ModalShell>

<style>
    .sheet {
        display: flex;
        flex-direction: column;
        gap: 10px;
        font-size: 12px;
    }

    .sheet__scope {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin: 0;
        padding: 8px 10px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 4px;
    }

    .sheet__theme-effects {
        margin: 6px 0 0;
        padding: 8px 10px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 4px;
    }

    .sheet__advanced {
        align-self: flex-start;
        padding: 0;
        border: 0;
        background: none;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 11px;
        text-decoration: underline;
        cursor: pointer;
    }

    .sheet__advanced-body {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .sheet__scripts-lead {
        margin: 0;
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.45;
    }

    .sheet__legend {
        padding: 0 4px;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .sheet__radio {
        display: grid;
        grid-template-columns: auto 1fr;
        align-items: baseline;
        gap: 2px 8px;
        cursor: pointer;
    }

    .sheet__radio-label {
        color: var(--oc-text-primary);
    }

    .sheet__radio-detail {
        grid-column: 2;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }

    .sheet__field {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .sheet__field-label {
        color: var(--oc-text-secondary);
    }

    .sheet__select {
        flex: 1;
        min-width: 0;
        padding: 3px 6px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 3px;
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-size: 12px;
    }

    .sheet__note {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }

    .sheet__refusal {
        margin: 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-coral);
        background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-raised));
        color: var(--oc-text-primary);
        line-height: 1.4;
    }

    @media (max-width: 767px) {
        .modal-btn,
        .sheet__advanced,
        .sheet__radio,
        .sheet__select {
            min-height: 44px;
        }

        .sheet__radio {
            align-items: center;
        }
    }
</style>
