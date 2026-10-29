
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import NumberField from '../base/NumberField.svelte';
    import Select from '../base/Select.svelte';
    import State from '../base/State.svelte';
    import Switch from '../base/Switch.svelte';
    import CopyField from './CopyField.svelte';
    import AgentToolChecks from './mcp-panel/AgentToolChecks.svelte';
    import TrustedProxies from './mcp-panel/TrustedProxies.svelte';
    import { MCP_FEATURES } from './mcp-panel/features';
    import './panel-kit/panel-kit.css';
    import { errorText } from './panel-kit/error-text';
    import {
        connectSnippets, fetchStatus, fetchTokens, mintToken, revokeToken, setEnabled, setTrustedProxies,
        type Fetcher, type McpStatus, type McpToken,
    } from './mcp-panel/api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let status = $state<McpStatus | null>(null);
    let tokens = $state<McpToken[]>([]);
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');
    let name = $state('');
    let scope = $state<'read' | 'write'>('read');
    let days = $state<number | null>(null);
    let secret = $state<{ name: string; value: string } | null>(null);
    let revoking = $state<string | null>(null);
    let confirmingOff = $state(false);

    const snippets = $derived(status ? connectSnippets(status.endpoint) : null);

    async function load(): Promise<void> {
        try {
            [status, tokens] = await Promise.all([fetchStatus(fetcher), fetchTokens(fetcher)]);
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function act(run: () => Promise<void>): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        try {
            await run();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
            await load();
        }
    }

    const toggle = (next: boolean): Promise<void> => act(async () => {
        confirmingOff = false;
        await setEnabled(next, fetcher);
        note = t('settings.mcp.restart_note');
    });
    const flip = (next: boolean): void => {
        if (next) void toggle(true);
        else confirmingOff = true;
    };
    const mint = (): Promise<void> => act(async () => {
        const made = await mintToken(name.trim(), scope, days !== null && Number.isFinite(days) && days > 0 ? Math.floor(days) : null, fetcher);
        secret = { name: made.token.name, value: made.secret };
        name = '';
        days = null;
    });
    const revoke = (id: string): Promise<void> => act(async () => {
        await revokeToken(id, fetcher);
        revoking = null;
    });
    const saveProxies = (next: string[]): Promise<void> => act(async () => {
        await setTrustedProxies(next, fetcher);
    });
    const when = (epoch: number | null): string => (epoch === null ? t('settings.mcp.never') : new Date(epoch * 1000).toLocaleString());
</script>

{#snippet features()}
    <ul class="mcp-panel__list" data-mcp="features">
        {#each MCP_FEATURES as id (id)}
            <li data-mcp-feature={id}>{t(`settings.mcp.feat.${id}`)}</li>
        {/each}
    </ul>
{/snippet}

<div class="tm" data-mcp="panel">
    {#if status && snippets}
        <p class="tm__sub" data-mcp="what">{t('settings.mcp.what')}</p>
        {#if status.enabled}
            <p class="tm__sub">{t('settings.mcp.rides')}</p>
            {@render features()}
        {/if}

        <Switch label={t('settings.mcp.enabled')} bind:checked={() => status?.enabled ?? false, flip} disabled={busy}
            data-mcp="switch" />
        <p class="tm__sub">{t('settings.mcp.enabled_hint')}</p>

        <AgentToolChecks {t} {fetcher} />

        {#if !status.enabled}
            <State kind="warn" title={t('settings.mcp.off_title')} hint={t('settings.mcp.off_after')} data-mcp="off-warning">
                {#snippet children()}{@render features()}{/snippet}
            </State>
        {:else if confirmingOff}
            <State kind="warn" title={t('settings.mcp.confirm_title')} hint={t('settings.mcp.off_after')} data-mcp="off-confirm">
                {#snippet children()}{@render features()}{/snippet}
                {#snippet actions()}
                    <Button data-mcp="off-keep" disabled={busy} onclick={() => (confirmingOff = false)}>{t('settings.mcp.confirm_keep')}</Button>
                    <Button variant="danger" data-mcp="off-go" disabled={busy} onclick={() => void toggle(false)}>{t('settings.mcp.confirm_off')}</Button>
                {/snippet}
            </State>
        {/if}

        <div class="tm__field">
            <p class="tm__sub">{t('settings.mcp.endpoint')}</p>
            <CopyField value={status.endpoint} {t} label={t('settings.mcp.endpoint')}
                valueAttrs={{ 'data-mcp': 'endpoint' }} buttonAttrs={{ 'data-mcp': 'copy-endpoint' }} />
        </div>

        <p class="tm__sub" data-mcp="gate">
            {t(status.gate_cross_session_actions ? 'settings.mcp.gate_on' : 'settings.mcp.gate_off')}
        </p>

        <p class="tm__sub" data-mcp="tools">
            <a class="tm__link" href="#docs/mcp" data-mcp="tools-link">{t('settings.mcp.tools_link', { count: status.tools.length })}</a>
        </p>

        <div class="tm__field" data-mcp="tokens">
            <p class="tm__sub">{t('settings.mcp.tokens')}</p>
            <p class="tm__sub">{t('settings.mcp.tokens_hint')}</p>
            {#if secret}
                <State kind="warn" title={t('settings.mcp.secret_once', { name: secret.name })} data-mcp="secret">
                    {#snippet children()}
                        <CopyField value={secret!.value} {t} label={t('settings.mcp.secret_label')}
                            valueAttrs={{ 'data-mcp': 'secret-value' }} buttonAttrs={{ 'data-mcp': 'copy-secret' }} />
                    {/snippet}
                    {#snippet actions()}
                        <Button data-mcp="dismiss-secret" onclick={() => (secret = null)}>{t('settings.mcp.done')}</Button>
                    {/snippet}
                </State>
            {/if}
            {#if tokens.length === 0}
                <p class="tm__sub" data-mcp="no-tokens">{t('settings.mcp.no_tokens')}</p>
            {:else}
                <List label={t('settings.mcp.tokens')}>
                    {#snippet children()}
                        {#each tokens as token (token.id)}
                            <ListRow wrap data-mcp="token" data-mcp-token-name={token.name}
                                primary={token.name}
                                secondary={t(token.scope === 'write' ? 'settings.mcp.scope_write' : 'settings.mcp.scope_read')}>
                                {#snippet actions()}
                                    {#if revoking !== token.id}
                                        <Button variant="danger" size="sm" data-mcp="revoke" disabled={busy} onclick={() => (revoking = token.id)}>{t('settings.mcp.revoke')}</Button>
                                    {/if}
                                {/snippet}
                                {#snippet below()}
                                    {t('settings.mcp.token_dates', {
                                        created: when(token.created_at), used: when(token.last_used_at),
                                        expires: token.expires_at === null ? t('settings.mcp.no_expiry') : when(token.expires_at),
                                    })}
                                    {#if revoking === token.id}
                                        <State kind="warn" title={t('settings.mcp.revoke_warning', { name: token.name })} data-mcp="revoke-warn">
                                            {#snippet actions()}
                                                <Button data-mcp="revoke-cancel" disabled={busy} onclick={() => (revoking = null)}>{t('settings.mcp.cancel')}</Button>
                                                <Button variant="danger" data-mcp="revoke-confirm" disabled={busy} onclick={() => void revoke(token.id)}>{t('settings.mcp.revoke_confirm')}</Button>
                                            {/snippet}
                                        </State>
                                    {/if}
                                {/snippet}
                            </ListRow>
                        {/each}
                    {/snippet}
                </List>
            {/if}

            <form class="tm__field" onsubmit={(event) => { event.preventDefault(); void mint(); }}>
                <Field maxlength={60} bind:value={name} disabled={busy} data-mcp="name"
                    placeholder={t('settings.mcp.name_placeholder')} aria-label={t('settings.mcp.name_label')} />
                <Select bind:value={scope} disabled={busy} data-mcp="scope" aria-label={t('settings.mcp.scope_label')}
                    options={[{ value: 'read', label: t('settings.mcp.scope_read') }, { value: 'write', label: t('settings.mcp.scope_write') }]} />
                <NumberField min={1} max={3650} bind:value={days} disabled={busy} data-mcp="days"
                    placeholder={t('settings.mcp.days_placeholder')} aria-label={t('settings.mcp.days_label')} />
                <div class="tm__actions">
                    <Button type="submit" variant="confirm" data-mcp="mint" disabled={busy || !name.trim()}>
                        {t('settings.mcp.mint')}
                    </Button>
                </div>
            </form>
        </div>

        <TrustedProxies {t} hosts={status.trusted_proxy_hosts ?? []} {busy} onSave={saveProxies} />

        <div class="tm__field" data-mcp="connect">
            <p class="tm__sub">{t('settings.mcp.connect')}</p>
            <p class="tm__sub">{t('settings.mcp.connect_hint')}</p>
            {#each [{ key: 'claude', label: 'settings.mcp.snippet_claude', text: snippets.claude }, { key: 'desktop', label: 'settings.mcp.snippet_desktop', text: snippets.desktop }, { key: 'ssh', label: 'settings.mcp.snippet_ssh', text: snippets.ssh }] as snip (snip.key)}
                <p class="tm__sub">{t(snip.label)}</p>
                <CopyField value={snip.text} {t} label={t(snip.label)}
                    valueAttrs={{ 'data-mcp': `snippet-${snip.key}` }} buttonAttrs={{ 'data-mcp': `copy-${snip.key}` }} />
            {/each}
        </div>

        <div class="tm__field" data-mcp="docs">
            <p class="tm__sub">{t('settings.mcp.docs')}</p>
            <details>
                <summary class="tm__sub">{t('settings.mcp.guide')}</summary>
                <Field multiline readonly block rows={12} value={status.guide} data-mcp="guide" aria-label={t('settings.mcp.guide')} />
            </details>
        </div>
    {:else if !problem}
        <p class="tm__sub">{t('settings.mcp.loading')}</p>
    {/if}
    {#if note}<State inline title={note} role="status" data-mcp="note" />{/if}
    {#if problem}<State kind="error" inline title={problem} data-mcp="problem" />{/if}
</div>

<style>
    @layer components {
          .mcp-panel__list { margin: 0; padding-left: var(--oc-space-4); display: flex; flex-direction: column; gap: var(--oc-space-1);
              font-family: var(--font-mono); font-size: var(--oc-fs-label); color: var(--oc-text-secondary); }
  

    }
</style>
