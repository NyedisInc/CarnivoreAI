
<script lang="ts">
    import Button from '../base/Button.svelte';
    import State from '../base/State.svelte';
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import './panel-kit/panel-kit.css';
    import './phone-link/custom-domain.css';
    import './tui-cli/tui-cli.css';
    import CopyField from './CopyField.svelte';
    import { errorText } from './panel-kit/error-text';
    import { getCliCommand, installCliCommand, type CliCommand, type CliOutcome, type CliState, type Fetcher } from './tui-cli/api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    const SHOT = '/static/img/tui/tui-sessions.svg';
    const USE_STEPS = ['ssh', 'run', 'login', 'keys'] as const;

    const shq = (v: string): string => `'${v.replace(/'/g, `'\\''`)}'`;

    let info = $state<CliCommand | null>(null);
    let cliState = $state<CliState | null>(null);
    let waiting = $state(false);
    let outcome = $state<CliOutcome | null>(null);
    let problem = $state('');

    const lamp = (s: CliState): 'ok' | 'wait' | 'bad' => (s === 'installed' ? 'ok' : s === 'foreign' ? 'bad' : 'wait');

    async function load(): Promise<void> {
        try {
            info = await getCliCommand(fetcher);
            cliState = info.state;
            problem = '';
        } catch (error) {
            problem = errorText(error);
        }
    }
    onMount(() => void load());

    async function install(): Promise<void> {
        waiting = true;
        outcome = null;
        problem = '';
        try {
            const result = await installCliCommand(fetcher);
            outcome = result.outcome;
            cliState = result.state;
        } catch (error) {
            outcome = 'failed';
            problem = errorText(error);
        } finally {
            waiting = false;
        }
        if (outcome === 'installed' || outcome === 'already_installed') await load();
    }
</script>

<div class="tm" data-tui="panel">
    <p class="tm__sub" data-tui="about">{t('settings.tui_cli.about')}</p>

    <div class="tui-cli__block">
        <h4 class="oc-label">{t('settings.tui_cli.use.title')}</h4>
        <ol class="tui-cli__steps" data-tui="steps">
            {#each USE_STEPS as step (step)}<li>{t(`settings.tui_cli.use.${step}`)}</li>{/each}
        </ol>
    </div>

    <img class="tui-cli__shot" src={SHOT} alt={t('settings.tui_cli.shot.alt')} data-tui="shot" />

    <div class="tui-cli__block">
        <h4 class="oc-label">{t('settings.tui_cli.install.title')}</h4>
        {#if info && cliState}
            <p class="cd-state" data-tui="state" data-tui-state={cliState}>
                <span class="cd-led cd-led--{lamp(cliState)}" aria-hidden="true"></span>
                <span>{t(`settings.tui_cli.state.${cliState}`)}</span>
                {#if cliState === 'installed'}<code data-tui="command">{info.command}</code>{/if}
            </p>
            {#if cliState === 'installed'}
                <CopyField value={info.command} {t} label={t('settings.tui_cli.launch.label')}
                    valueAttrs={{ 'data-tui': 'launch' }} buttonAttrs={{ 'data-tui': 'launch-copy' }} />
                <p class="tm__sub" data-tui="location">{t('settings.tui_cli.launch.location', { link: info.link_path, shim: info.shim_path })}</p>
            {:else if cliState !== 'foreign'}
                <p class="tm__sub">{t('settings.tui_cli.launch.not_installed')}</p>
                <CopyField value={`${shq(info.shim_path)} tui`} {t} label={t('settings.tui_cli.launch.label')}
                    valueAttrs={{ 'data-tui': 'launch' }} buttonAttrs={{ 'data-tui': 'launch-copy' }} />
            {/if}
            {#if cliState === 'foreign'}<State kind="error" inline data-tui="foreign" title={t('settings.tui_cli.foreign.note')} />{/if}
            {#if cliState === 'missing' || cliState === 'stale'}
                <div>
                    <Button variant="confirm" data-tui="install" disabled={waiting} onclick={() => void install()}>
                        {t('settings.tui_cli.button')}
                    </Button>
                </div>
            {/if}
        {:else if !problem}
            <p class="tm__sub" data-tui="loading">{t('settings.tui_cli.loading')}</p>
        {/if}
        {#if waiting}<p class="tm__sub" role="status" data-tui="waiting">{t('settings.tui_cli.waiting')}</p>{/if}
        {#if outcome}
            <State kind={outcome === 'installed' || outcome === 'already_installed' ? 'empty' : 'error'} inline role="status" data-tui="outcome" data-tui-outcome={outcome}
                title={t(`settings.tui_cli.outcome.${outcome}`)} />
        {/if}
        {#if problem}<State kind="error" inline data-tui="problem" title={problem} />{/if}
    </div>

    {#if info}
        <div class="tui-cli__block">
            <h4 class="oc-label">{t('settings.tui_cli.manual.title')}</h4>
            <CopyField value={info.manual_command} {t} label={t('settings.tui_cli.manual.label')}
                valueAttrs={{ 'data-tui': 'manual' }} buttonAttrs={{ 'data-tui': 'manual-copy' }} />
        </div>
        <div class="tui-cli__block">
            <h4 class="oc-label">{t('settings.tui_cli.checkout.title')}</h4>
            <CopyField value={info.run_from_checkout} {t} label={t('settings.tui_cli.checkout.label')}
                valueAttrs={{ 'data-tui': 'checkout' }} buttonAttrs={{ 'data-tui': 'checkout-copy' }} />
        </div>
    {/if}
</div>
