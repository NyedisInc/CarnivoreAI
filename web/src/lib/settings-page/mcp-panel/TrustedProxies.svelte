
<script lang="ts">
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import Button from '../../base/Button.svelte';
    import Field from '../../base/Field.svelte';
    import List from '../../base/List.svelte';
    import ListRow from '../../base/ListRow.svelte';
    import State from '../../base/State.svelte';
    import { checkProxyEntry } from './trusted-proxy';

    interface Props {
        t?: Translate;
        hosts: readonly string[];
        busy?: boolean;
        onSave: (next: string[]) => Promise<void>;
    }
    const { t = reactiveT, hosts, busy = false, onSave }: Props = $props();

    let entry = $state('');
    let problem = $state('');
    let removing = $state<string | null>(null);

    async function add(): Promise<void> {
        const check = checkProxyEntry(entry, hosts);
        if (!check.ok) {
            problem = t(`settings.mcp.proxy_err_${check.problem}`);
            return;
        }
        problem = '';
        await onSave([...hosts, check.host]);
        entry = '';
    }

    async function remove(host: string): Promise<void> {
        removing = null;
        await onSave(hosts.filter((h) => h !== host));
    }
</script>

<div class="tm__field" data-mcp="proxies">
    <p class="tm__sub">{t('settings.mcp.proxies')}</p>
    <p class="tm__sub">{t('settings.mcp.proxies_hint')}</p>
    {#if hosts.length === 0}
        <p class="tm__sub" data-mcp="no-proxies">{t('settings.mcp.proxy_none')}</p>
    {:else}
        <List label={t('settings.mcp.proxies')}>
            {#snippet children()}
                {#each hosts as host (host)}
                    <ListRow wrap data-mcp="proxy" data-mcp-proxy-host={host} primary={host}>
                        {#snippet actions()}
                            {#if removing !== host}
                                <Button variant="danger" size="sm" data-mcp="proxy-remove" disabled={busy} onclick={() => (removing = host)}>{t('settings.mcp.proxy_remove')}</Button>
                            {/if}
                        {/snippet}
                        {#snippet below()}
                            {#if removing === host}
                                <State kind="warn" title={t('settings.mcp.proxy_remove_warning', { host })} data-mcp="proxy-remove-warn">
                                    {#snippet actions()}
                                        <Button data-mcp="proxy-remove-cancel" disabled={busy} onclick={() => (removing = null)}>{t('settings.mcp.cancel')}</Button>
                                        <Button variant="danger" data-mcp="proxy-remove-confirm" disabled={busy} onclick={() => void remove(host)}>{t('settings.mcp.proxy_remove_confirm')}</Button>
                                    {/snippet}
                                </State>
                            {/if}
                        {/snippet}
                    </ListRow>
                {/each}
            {/snippet}
        </List>
    {/if}

    <form class="tm__field" onsubmit={(event) => { event.preventDefault(); void add(); }}>
        <Field maxlength={64} bind:value={entry} disabled={busy} data-mcp="proxy-entry"
            placeholder={t('settings.mcp.proxy_placeholder')} aria-label={t('settings.mcp.proxy_label')} />
        <div class="tm__actions">
            <Button type="submit" variant="confirm" data-mcp="proxy-add" disabled={busy || !entry.trim()}>
                {t('settings.mcp.proxy_add')}
            </Button>
        </div>
    </form>
    {#if problem}<State kind="error" inline title={problem} data-mcp="proxy-problem" />{/if}
</div>
