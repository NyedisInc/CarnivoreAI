
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { authFetch } from '../../opscenter/api/auth.svelte';
    import SettingsForm from '../item-settings/SettingsForm.svelte';
    import SettingsMatrix from '../item-settings/SettingsMatrix.svelte';
    import type { SettingValue } from '../item-settings/api';
    import '../settings-page/panel-kit/panel-kit.css';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import { gridFields, gridMatrix, gridValues, scopeSchema, TRUST_SCOPE_KEY, type BeastRules } from './grid-model';

    interface Props {
        t?: Translate;
        fetcher?: typeof authFetch;
    }
    const { t = reactiveT, fetcher = authFetch }: Props = $props();

    const ROUTE = '/beast-mode/rules';
    let rules = $state<BeastRules | null>(null);
    let busy = $state(false);
    let problem = $state<{ key: string; text: string } | null>(null);
    let loadProblem = $state('');

    async function load(): Promise<void> {
        try {
            rules = await fetcher<BeastRules>(ROUTE);
        } catch (error) {
            loadProblem = errorText(error);
        }
    }
    void load();

    async function change(key: string, value: SettingValue | null): Promise<void> {
        if (busy || !rules) return;
        busy = true;
        problem = null;
        const fallback = rules.cells[key]?.default;
        const body = key === TRUST_SCOPE_KEY ? { trust_scope: value ?? 'projects' } : { cells: { [key]: value ?? fallback } };
        try {
            rules = await fetcher<BeastRules>(ROUTE, { method: 'PUT', body: JSON.stringify(body) });
        } catch (error) {
            problem = { key, text: errorText(error) };
        } finally {
            busy = false;
        }
    }
</script>

<div class="tm" data-beast-grid="panel">
    {#if rules}
        <SettingsMatrix matrix={gridMatrix(rules)} fields={gridFields(rules)} values={gridValues(rules)} {t} onChange={(key, value) => void change(key, value)}
            {busy} error={problem} idPrefix="beast-grid" />
        <SettingsForm schema={scopeSchema(rules)} values={rules.trust_scope === 'projects' ? {} : { [TRUST_SCOPE_KEY]: rules.trust_scope }} {t} onChange={(key, value) => void change(key, value)}
            busyKey={busy ? TRUST_SCOPE_KEY : null} error={problem} idPrefix="beast-scope" heading={false} />
    {:else if !loadProblem}
        <p class="tm__sub">{t('beast.settings.loading')}</p>
    {/if}
    {#if loadProblem}<p class="tm__problem" role="alert">{loadProblem}</p>{/if}
</div>
