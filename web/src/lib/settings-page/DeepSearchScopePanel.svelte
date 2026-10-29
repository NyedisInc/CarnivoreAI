
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import RadioGroup from '../base/RadioGroup.svelte';
    import State from '../base/State.svelte';
    import './panel-kit/panel-kit.css';
    import { INDEX_SCOPES, fetchScope, saveScope, scopeKey, type IndexScope } from '../deepsearch/scope-api';
    import { errorText } from './panel-kit/error-text';

    interface Props {
        t?: Translate;
        load?: () => Promise<IndexScope>;
        save?: (scope: IndexScope) => Promise<string | null>;
    }
    const { t = reactiveT, load = () => fetchScope(), save = saveScope }: Props = $props();

    let scope = $state<IndexScope | null>(null);
    let busy = $state(false);
    let problem = $state('');
    let redraw = $state(0);

    async function refresh(): Promise<void> {
        try {
            scope = await load();
        } catch (error) {
            problem = errorText(error);
        }
    }
    void refresh();

    async function choose(next: IndexScope): Promise<void> {
        busy = true;
        problem = '';
        try {
            const failure = await save(next);
            if (failure) problem = failure;
            else scope = next;
        } catch (error) {
            problem = errorText(error);
        } finally {
            if (scope !== next) redraw += 1;
            busy = false;
        }
    }
</script>

<div class="tm" data-deepsearch-scope="panel">
    {#if scope}
        <div aria-busy={busy} data-deepsearch-scope="choices">
            {#key redraw}<RadioGroup label={t('settings.deepsearch_scope.group')} disabled={busy}
                bind:value={() => scope ?? '', (choice) => { if (!busy && scope !== choice) void choose(choice as IndexScope); }}
                options={INDEX_SCOPES.map((choice) => ({ value: choice, label: t(scopeKey(choice)), hint: t(`${scopeKey(choice)}.desc`) }))} />{/key}
        </div>
    {:else if !problem}
        <p class="tm__sub">{t('settings.deepsearch_scope.loading')}</p>
    {/if}
    {#if problem}<State kind="error" inline title={problem} />{/if}
</div>
