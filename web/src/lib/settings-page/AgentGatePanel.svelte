
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Button from '../base/Button.svelte';
    import State from '../base/State.svelte';
    import Switch from '../base/Switch.svelte';
    import './panel-kit/panel-kit.css';
    import { authFetch } from '../../opscenter/api/auth.svelte';
    import { errorText } from './panel-kit/error-text';
    import { BEAST_SETTINGS_HASH } from '../beast-mode/settings-link';

    interface Props {
        t?: Translate;
        fetcher?: typeof authFetch;
    }
    const { t = reactiveT, fetcher = authFetch }: Props = $props();

    const ROUTE = '/agent-actions/settings';
    let gate = $state<boolean | null>(null);
    let busy = $state(false);
    let problem = $state('');

    async function load(): Promise<void> {
        try {
            gate = (await fetcher<{ gate_cross_session_actions: boolean }>(ROUTE)).gate_cross_session_actions;
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function save(next: boolean): Promise<void> {
        busy = true;
        problem = '';
        try {
            gate = (await fetcher<{ gate_cross_session_actions: boolean }>(ROUTE, {
                method: 'PUT',
                body: JSON.stringify({ gate_cross_session_actions: next }),
            })).gate_cross_session_actions;
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }
</script>

<div class="tm" data-agent-gate="panel">
    {#if gate !== null}
        <Switch label={t('settings.agent_gate.label')} bind:checked={() => gate ?? false, (next) => void save(next)} disabled={busy}
            data-agent-gate="switch" />
        <p class="tm__sub">{t('settings.agent_gate.hint')}</p>
    {:else if !problem}
        <p class="tm__sub">{t('settings.agent_gate.loading')}</p>
    {/if}
    {#if problem}<State kind="error" inline title={problem} />{/if}
    <section class="agent-gate__beast" data-agent-gate="beast">
        <div class="agent-gate__beast-head">
            <Icon name="bolt" size={14} />
            <span class="agent-gate__beast-label" data-agent-gate="beast-label">{t('settings.agent_gate.beast_label')}</span>
        </div>
        <p class="tm__sub" data-agent-gate="beast-what">{t('settings.agent_gate.beast_what')}</p>
        <p class="tm__sub" data-agent-gate="beast-where">{t('settings.agent_gate.beast_where')}</p>
        <p class="tm__sub agent-gate__beast-risk" data-agent-gate="beast-risk">{t('settings.agent_gate.beast_risk')}</p>
        <div class="agent-gate__beast-foot">
            <Button data-agent-gate="beast-settings" href={BEAST_SETTINGS_HASH}>{t('settings.agent_gate.beast_settings')}</Button>
        </div>
    </section>
</div>

<style>
    @layer components {
          .agent-gate__beast { display: flex; flex-direction: column; gap: var(--oc-space-2); margin-top: var(--oc-space-3);
              padding-top: var(--oc-space-3); border-top: 1px solid var(--oc-line-panel); }
          .agent-gate__beast-head { display: flex; align-items: center; gap: var(--oc-space-2); color: var(--oc-orange); }
          .agent-gate__beast-label { font-family: var(--font-mono); font-size: var(--oc-fs-micro, 10px);
              letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }
          .agent-gate__beast-foot { display: flex; align-items: center; gap: var(--oc-space-2); flex-wrap: wrap; }
  

    .agent-gate__beast .agent-gate__beast-risk { color: var(--oc-coral); }
    }
</style>
