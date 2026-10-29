
<script lang="ts">
    import Button from '../base/Button.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import State from '../base/State.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import './panel-kit/panel-kit.css';
    import { errorText } from './panel-kit/error-text';
    import {
        enableAlerts,
        listSubscriptions,
        pushEnvironment,
        removeSubscription,
        sendTest,
        type Fetcher,
        type PushEnvironment,
        type PushSubscriptionRow,
    } from './web-push/api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
        env?: PushEnvironment;
        subscribe?: () => Promise<void>;
    }
    const { t = reactiveT, fetcher, env = pushEnvironment(), subscribe }: Props = $props();

    let rows = $state<PushSubscriptionRow[] | null>(null);
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');

    async function load(): Promise<void> {
        try {
            rows = await listSubscriptions(fetcher);
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function act(work: () => Promise<string>): Promise<void> {
        busy = true;
        note = '';
        problem = '';
        try {
            note = await work();
        } catch (error) {
            problem = error instanceof Error && error.message === 'denied' ? t('settings.web_push.denied') : errorText(error);
        } finally {
            busy = false;
        }
        await load();
    }

    const turnOn = () =>
        act(async () => {
            await (subscribe ?? (() => enableAlerts(fetcher)))();
            return t('settings.web_push.on_done');
        });
    const test = () =>
        act(async () => {
            const count = await sendTest(fetcher);
            return count === 0 ? t('settings.web_push.test_none') : t('settings.web_push.test_sent', { count });
        });
    const remove = (id: string) =>
        act(async () => {
            await removeSubscription(id, fetcher);
            return t('settings.web_push.removed');
        });

    function resultText(row: PushSubscriptionRow): string {
        return row.last_result
            ? t('settings.web_push.last', { status: row.last_result.status, at: row.last_result.at.slice(0, 16).replace('T', ' ') })
            : t('settings.web_push.never');
    }
</script>

<div class="tm" data-wp="panel">
    <p class="tm__sub">{t('settings.web_push.what')}</p>
    {#if env.supported && env.standalone}
        <div>
            <Button variant="confirm" data-wp="on" disabled={busy} onclick={() => void turnOn()}>
                {t('settings.web_push.on')}
            </Button>
        </div>
    {:else}
        <p class="tm__sub" data-wp="install-hint">{t('settings.web_push.install_hint')}</p>
    {/if}

    {#if rows && rows.length > 0}
        <List label={t('settings.web_push.what')} data-wp="list">
            {#snippet children()}
                {#each rows as row (row.id)}
                    <ListRow data-wp-row={row.id} primary={`${row.service}: ${resultText(row)}`}>
                        {#snippet actions()}
                            <Button variant="danger" size="sm" data-wp="remove" disabled={busy} onclick={() => void remove(row.id)}>
                                {t('settings.web_push.remove')}
                            </Button>
                        {/snippet}
                    </ListRow>
                {/each}
            {/snippet}
        </List>
        <div>
            <Button data-wp="test" disabled={busy} onclick={() => void test()}>
                {t('settings.web_push.test')}
            </Button>
        </div>
    {:else if rows}
        <p class="tm__sub" data-wp="empty">{t('settings.web_push.empty')}</p>
    {/if}
    {#if note}<State inline role="status" data-wp="note" title={note} />{/if}
    {#if problem}<State kind="error" inline data-wp="problem" title={problem} />{/if}
</div>
