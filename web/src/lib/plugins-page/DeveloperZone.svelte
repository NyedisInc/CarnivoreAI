
<script lang="ts">
    import Button from '../base/Button.svelte';
    import type { Translate } from '../sessions/types';
    import SideloadSwitch from './SideloadSwitch.svelte';
    import ThirdPartySwitch from './ThirdPartySwitch.svelte';
    import type { SideloadStore } from './sideload-store.svelte';
    import { untilWhen } from './sideload-switch';

    const DEVELOPER_ZONE_OPEN_KEY = 'plugins.developerZone.open';

    interface Props {
        t: Translate;
        sideloads: SideloadStore | null;
    }

    const { t, sideloads }: Props = $props();

    function readOpen(): boolean {
        try {
            return localStorage.getItem(DEVELOPER_ZONE_OPEN_KEY) === '1';
        } catch {
            return false;
        }
    }

    let open = $state(readOpen());
    let thirdParty = $state<boolean | null>(null);

    const until = $derived(untilWhen(sideloads?.status ?? null, t));

    function toggle(): void {
        open = !open;
        try {
            localStorage.setItem(DEVELOPER_ZONE_OPEN_KEY, open ? '1' : '0');
        } catch {
        }
    }
</script>

<section class="dev-zone" aria-label={t('plugins.page.developer.label')} data-developer-zone data-open={open ? '1' : '0'} data-sideload-on={until ? '1' : '0'}>
    <div class="dev-zone__line">
        <span class="dev-zone__label">{t('plugins.page.developer.label')}</span>
        {#if until}
            <span class="dev-zone__warn" role="status" data-sideload-summary>{t('plugins.page.developer.sideload_on', { when: until })}</span>
        {/if}
        {#if thirdParty !== null}
            <span class="dev-zone__state" data-third-party-summary>{t(thirdParty ? 'plugins.page.developer.third_party_on' : 'plugins.page.developer.third_party_off')}</span>
        {/if}
        <span class="dev-zone__sp"></span>
        <Button size="sm" aria-expanded={open} aria-controls="developer-zone-controls" data-developer-manage onclick={toggle}>
            {t('plugins.page.developer.manage')}<span class="dev-zone__caret" aria-hidden="true"></span>
        </Button>
    </div>
    <div class="dev-zone__row" id="developer-zone-controls" hidden={!open} data-developer-controls>
        <ThirdPartySwitch {t} onStatus={(status) => (thirdParty = status.enabled)} />
        {#if sideloads}<SideloadSwitch {t} store={sideloads} showStrip={false} />{/if}
    </div>
</section>

<style>
    @layer components {
        .dev-zone {
            min-width: 0;
            font-family: var(--font-mono);
        }

        .dev-zone__line {
            display: flex;
            align-items: center;
            gap: var(--oc-space-4);
            height: 30px;
            min-width: 0;
            padding: 0 var(--oc-space-4);
            background: var(--oc-ground-titlerow);
            box-shadow: inset 0 -1px 0 var(--oc-line-rule);
            font-size: var(--oc-fs-label, 11px);
            white-space: nowrap;
        }

        .dev-zone__label {
            flex: none;
            color: var(--oc-orange);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
        }

        .dev-zone__warn {
            flex: 0 1 auto;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            color: var(--oc-coral);
        }

        .dev-zone__state {
            flex: none;
            color: var(--oc-text-secondary);
        }

        .dev-zone__sp {
            flex: 1 1 0;
            min-width: 0;
        }

        .dev-zone__line :global([data-developer-manage]) {
            flex: none;
        }

        .dev-zone__caret {
            width: 6px;
            height: 6px;
            margin-left: var(--oc-space-2);
            border-right: 1px solid currentColor;
            border-bottom: 1px solid currentColor;
            transform: rotate(45deg) translate(-1px, -1px);
        }

        :global([data-developer-manage][aria-expanded='true']) .dev-zone__caret {
            transform: rotate(-135deg) translate(-1px, -1px);
        }

        .dev-zone__row {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-1) var(--oc-space-4);
            min-height: 36px;
            min-width: 0;
            padding: var(--oc-space-1) var(--oc-space-4) var(--oc-space-1) calc(var(--oc-space-5) + var(--oc-space-1));
            background: var(--oc-ground-raised);
            box-shadow: inset 0 -1px 0 var(--oc-line-rule);
        }

        .dev-zone__row[hidden] {
            display: none;
        }

        .dev-zone__row :global(.plp-note) {
            margin: 0;
        }

        .dev-zone__row :global([data-sideload-open='folder']) {
            margin-left: auto;
        }

        @media (max-width: 700px) {
            .dev-zone[data-sideload-on='1'] .dev-zone__state {
                display: none;
            }

            .dev-zone__line {
                gap: var(--oc-space-2);
                padding: 0 var(--oc-space-3);
            }

            .dev-zone__row {
                gap: var(--oc-space-1) var(--oc-space-3);
                padding: var(--oc-space-2) var(--oc-space-3);
            }
        }
    }
</style>
