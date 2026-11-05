
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import Button from '../base/Button.svelte';
    import ConsentScripts from '../catalog/ConsentScripts.svelte';
    import PreviewFacts from '../catalog/InstallPreview.svelte';
    import PluginFacts from '../catalog/PluginFacts.svelte';
    import { mcpServers } from '../catalog/mcp';
    import { pluginFacts } from '../catalog/plugin-facts';
    import { consentBlock, scriptFiles } from '../catalog/scripts';
    import type { InstallConsent } from '../catalog/types';
    import type { Translate } from '../sessions/types';
    import { refusalText, type SideloadSheet } from './sideload-switch';
    import './plugin-pane.css';

    interface Props {
        sheet: SideloadSheet;
        t: Translate;
        onConfirm: (consent: InstallConsent) => Promise<void>;
        onCancel: () => void;
    }

    const { sheet, t, onConfirm, onCancel }: Props = $props();

    let accepted = $state(false);
    let busy = $state(false);
    let error = $state<string | null>(null);

    const block = $derived(consentBlock(sheet));
    const servers = $derived(mcpServers(sheet));
    const plugin = $derived(sheet.kind === 'plugin' || servers.length > 0 ? pluginFacts(sheet.kind === 'plugin' ? (sheet.body ?? null) : null, sheet.files ?? null) : null);

    async function confirm(): Promise<void> {
        if (!block || !accepted || busy) return;
        busy = true;
        error = null;
        try {
            await onConfirm(block);
        } catch (failure) {
            error = refusalText(failure, t);
        } finally {
            busy = false;
        }
    }
</script>

<div class="sideload-consent" data-sideload-consent={sheet.kind ?? ''}>
    <p class="sideload-consent__title">{t('plugins.page.sideload.consent.title', { name: sheet.name ?? '' })}</p>
    <div class="sideload-consent__body">
        <p class="plp-warn" role="status">{t(SKILL_KEYS.consentReadFirst)}</p>
        <PreviewFacts preview={sheet} kind={sheet.kind ?? null} {t} />
        {#if plugin}<PluginFacts facts={plugin} mcp={servers} {t} />{/if}
        <ConsentScripts scripts={scriptFiles(sheet)} {t} {accepted} expressible={block !== null} {busy} onAccept={(next) => (accepted = next)} />
    </div>
    {#if error}<p class="plp__error" role="alert" data-sideload-consent-error>{error}</p>{/if}
    <div class="sideload-consent__foot">
        <Button size="sm" data-sideload-consent-cancel="1" onclick={onCancel}>{t('plugins.page.sideload.cancel')}</Button>
        <Button size="sm" variant="confirm" disabled={!block || !accepted || busy} data-sideload-consent-confirm="1" onclick={() => void confirm()}>
            {t('plugins.page.sideload.consent.load')}
        </Button>
    </div>
</div>

<style>
    @layer components {
        .sideload-consent {
            display: flex;
            flex-direction: column;
            width: min(420px, 100%);
            font-family: var(--font-mono);
        }

        .sideload-consent__title {
            margin: 0;
            padding: var(--oc-space-2) var(--oc-space-3);
            background: var(--oc-ground-titlerow);
            box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
            color: var(--oc-orange);
            font-size: var(--oc-fs-label, 11px);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
        }

        .sideload-consent__body {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
            max-height: 60vh;
            overflow: auto;
            padding: var(--oc-space-3);
        }

        .sideload-consent__foot {
            display: flex;
            justify-content: flex-end;
            gap: var(--oc-space-2);
            padding: var(--oc-space-2) var(--oc-space-3);
            box-shadow: inset 0 1px 0 0 var(--oc-line-rule);
        }
    }
</style>
