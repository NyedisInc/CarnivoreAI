
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import RadioGroup from '../base/RadioGroup.svelte';
    import State from '../base/State.svelte';
    import './panel-kit/panel-kit.css';
    import { authFetch } from '../../opscenter/api/auth.svelte';
    import { errorText } from './panel-kit/error-text';
    import { formatUntil, msUntilReread } from '../../opscenter/log/level-expiry';

    interface LogLevelState {
        level: string;
        source: 'setting' | 'env';
        env_level: string;
        choices: string[];
        expires_at: string | null;
    }

    interface Props {
        t?: Translate;
        fetcher?: typeof authFetch;
    }
    const { t = reactiveT, fetcher = authFetch }: Props = $props();

    const ROUTE = '/log-level';
    let levelState = $state<LogLevelState | null>(null);
    let busy = $state(false);
    let problem = $state('');
    let redraw = $state(0);

    async function load(): Promise<void> {
        try {
            levelState = await fetcher<LogLevelState>(ROUTE);
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    $effect(() => {
        const ends = levelState?.expires_at;
        const wait = ends ? msUntilReread(ends) : null;
        if (wait === null) return;
        const timer = setTimeout(() => void load(), wait);
        return () => clearTimeout(timer);
    });

    async function save(level: string | null): Promise<void> {
        busy = true;
        problem = '';
        try {
            levelState = await fetcher<LogLevelState>(ROUTE, { method: 'PUT', body: JSON.stringify({ level }) });
        } catch (error) {
            problem = errorText(error);
            redraw += 1;
        } finally {
            busy = false;
        }
    }
</script>

<div class="tm" data-log-level="panel">
    {#if levelState}
        <div aria-busy={busy} data-log-level="choices">
            {#key redraw}<RadioGroup label={t('settings.log_level.group')} disabled={busy}
                bind:value={() => levelState?.level ?? '', (choice) => { if (!busy && levelState?.level !== choice) void save(choice); }}
                options={(levelState.choices ?? []).map((choice) => ({ value: choice, label: t(`settings.log_level.${choice}`), hint: t(`settings.log_level.${choice}.desc`) }))} />{/key}
        </div>
        {#if levelState.expires_at}
            <p class="tm__sub" data-log-level="expires">{t('settings.log_level.source.temporary', { time: formatUntil(levelState.expires_at) })}</p>
        {:else}
            <p class="tm__sub" data-log-level="source">{t(`settings.log_level.source.${levelState.source}`)}</p>
        {/if}
        {#if levelState.source === 'setting' || levelState.expires_at}
            <div>
                <Button size="sm" data-log-level="reset" disabled={busy}
                    onclick={() => void save(null)}>{t('settings.log_level.reset')}</Button>
            </div>
        {/if}
    {:else if !problem}
        <p class="tm__sub">{t('settings.log_level.loading')}</p>
    {/if}
    {#if problem}<State kind="error" inline title={problem} />{/if}
</div>
