
<script lang="ts">
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import Button from '../../base/Button.svelte';
    import Field from '../../base/Field.svelte';
    import List from '../../base/List.svelte';
    import ListRow from '../../base/ListRow.svelte';
    import State from '../../base/State.svelte';
    import CopyField from '../CopyField.svelte';
    import '../panel-kit/panel-kit.css';
    import { errorText } from '../panel-kit/error-text';
    import { createKey, fetchKeys, revokeKey, type ApiKey, type Fetcher } from './api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let keys = $state<ApiKey[] | null>(null);
    let busy = $state(false);
    let problem = $state('');
    let name = $state('');
    let secret = $state<{ name: string; value: string } | null>(null);
    let revoking = $state<string | null>(null);

    async function load(): Promise<void> {
        try {
            keys = await fetchKeys(fetcher);
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function act(run: () => Promise<void>): Promise<void> {
        busy = true;
        problem = '';
        try {
            await run();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
            await load();
        }
    }

    const create = (): Promise<void> => act(async () => {
        const made = await createKey(name.trim(), fetcher);
        secret = { name: made.key.name, value: made.secret };
        name = '';
    });
    const revoke = (id: string): Promise<void> => act(async () => {
        await revokeKey(id, fetcher);
        revoking = null;
    });
    const when = (epoch: number | null): string => (epoch === null ? t('settings.api_keys.never') : new Date(epoch * 1000).toLocaleString());
</script>

<div class="tm" data-api-keys="panel">
    <p class="tm__sub">{t('settings.api_keys.what')}</p>
    <p class="tm__sub">{t('settings.api_keys.fence')}</p>

    {#if secret}
        <State kind="warn" title={t('settings.api_keys.secret_once', { name: secret.name })} data-api-keys="secret">
            {#snippet children()}
                <CopyField value={secret!.value} {t} label={t('settings.api_keys.secret_label')}
                    valueAttrs={{ 'data-api-keys': 'secret-value' }} buttonAttrs={{ 'data-api-keys': 'copy-secret' }} />
            {/snippet}
            {#snippet actions()}
                <Button data-api-keys="dismiss-secret" onclick={() => (secret = null)}>{t('settings.api_keys.done')}</Button>
            {/snippet}
        </State>
    {/if}

    {#if keys}
        {#if keys.length === 0}
            <p class="tm__sub" data-api-keys="none">{t('settings.api_keys.none')}</p>
        {:else}
            <List label={t('settings.api_keys.what')}>
                {#snippet children()}
                    {#each keys as key (key.id)}
                        <ListRow wrap data-api-keys="key" data-api-key-id={key.id} primary={key.name}>
                            {#snippet secondary()}<span data-api-keys="prefix">{key.display_prefix}</span>{/snippet}
                            {#snippet actions()}
                                {#if key.revoked_at === null && revoking !== key.id}
                                    <Button variant="danger" size="sm" data-api-keys="revoke" disabled={busy} onclick={() => (revoking = key.id)}>{t('settings.api_keys.revoke')}</Button>
                                {/if}
                            {/snippet}
                            {#snippet below()}
                                <span>{t('settings.api_keys.dates', { created: when(key.created_at), used: when(key.last_used_at) })}</span>
                                {#if key.revoked_at !== null}
                                    <span data-api-keys="revoked">{t('settings.api_keys.revoked_on', { when: when(key.revoked_at) })}</span>
                                {/if}
                                {#if revoking === key.id}
                                    <State kind="warn" title={t('settings.api_keys.revoke_warning', { name: key.name })} data-api-keys="revoke-warn">
                                        {#snippet actions()}
                                            <Button data-api-keys="revoke-cancel" disabled={busy} onclick={() => (revoking = null)}>{t('settings.api_keys.cancel')}</Button>
                                            <Button variant="danger" data-api-keys="revoke-confirm" disabled={busy} onclick={() => void revoke(key.id)}>{t('settings.api_keys.revoke_confirm')}</Button>
                                        {/snippet}
                                    </State>
                                {/if}
                            {/snippet}
                        </ListRow>
                    {/each}
                {/snippet}
            </List>
        {/if}

        <form class="tm__field" onsubmit={(event) => { event.preventDefault(); void create(); }}>
            <Field maxlength={60} bind:value={name} disabled={busy} data-api-keys="name"
                placeholder={t('settings.api_keys.name_placeholder')} aria-label={t('settings.api_keys.name_label')} />
            <div class="tm__actions">
                <Button type="submit" variant="confirm" data-api-keys="create" disabled={busy || !name.trim()}>
                    {t('settings.api_keys.create')}
                </Button>
            </div>
        </form>
    {:else if !problem}
        <p class="tm__sub">{t('settings.api_keys.loading')}</p>
    {/if}
    {#if problem}<State kind="error" inline title={problem} data-api-keys="problem" />{/if}
</div>
