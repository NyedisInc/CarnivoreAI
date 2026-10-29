
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { PRIVACY_URL } from '../carnivore-account/signin-flow';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import '../settings-page/panel-kit/panel-kit.css';
    import { fetchDisclosure, type Disclosure, type Fetcher } from './disclosure-api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let view = $state<Disclosure | null>(null);
    let problem = $state('');

    onMount(async () => {
        try {
            view = await fetchDisclosure(fetcher);
        } catch (error) {
            problem = errorText(error);
        }
    });
</script>

<div class="tm" data-install-report-panel>
    <p class="tm__sub">{t('privacy.install_report.panel.intro')}</p>
    {#if view}
        <p class="tm__sub">{t('privacy.install_report.panel.report_head')}</p>
        <ul class="irp" data-install-report-fields="report">
            {#each view.report as id (id)}
                <li><code>{id}</code> {t(`privacy.install_report.field.${id}`)}</li>
            {/each}
        </ul>
        <p class="tm__sub">{t('privacy.install_report.panel.guest_head')}</p>
        <ul class="irp" data-install-report-fields="guest">
            {#each view.guest as id (id)}
                <li><code>{id}</code> {t(`privacy.install_report.field.${id}`)}</li>
            {/each}
        </ul>
        <p class="tm__sub">{t('privacy.install_report.panel.every_request')}</p>
    {:else if problem}
        <p class="tm__problem" role="alert">{problem}</p>
    {:else}
        <p class="tm__sub">{t('privacy.install_report.panel.loading')}</p>
    {/if}
    <p class="tm__sub">
        {t('privacy.install_report.panel.no_switch')}
        <a class="tm__link" href={PRIVACY_URL} target="_blank" rel="noopener noreferrer">{t('privacy.install_report.notice.policy')}</a>
    </p>
</div>

<style>
  @layer components {
    .irp {
        margin: 0 0 8px;
        padding: 0;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: 4px;
        color: var(--oc-text-secondary);
        font-size: 12px;
        line-height: 1.5;
    }

    .irp li {
        padding-left: 8px;
        border-left: 2px solid var(--oc-line-rule);
        overflow-wrap: anywhere;
    }

    .irp code {
        font-family: var(--font-mono);
        color: var(--oc-text-primary);
    }
  }
</style>
