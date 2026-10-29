<!-- the plugins page -->
<script lang="ts">
    import { KIND_KEYS } from '../../../../client/js/labels/catalog-kind.js';
    import type { Translate } from '../sessions/types';
    import type { CplugFactsData } from './types';

    interface Props {
        facts: CplugFactsData | null;
        accepted: boolean;
        busy: boolean;
        t: Translate;
        onAccept: (next: boolean) => void;
    }

    const { facts, accepted, busy, t, onAccept }: Props = $props();

    const permissions = $derived(facts?.permissions ?? []);
    const tools = $derived(facts?.tools ?? []);
    const hosts = $derived(facts?.network_hosts ?? []);
    const lan = $derived(facts?.lan_hosts ?? []);
    const secrets = $derived(facts?.secrets ?? []);

    function schemaText(schema: unknown): string {
        try {
            return JSON.stringify(schema ?? {}, null, 2);
        } catch {
            return '{}';
        }
    }
</script>

<div class="cplugfacts">
    <p class="cplugfacts__trust" role="note">{t(KIND_KEYS.cplugTrust)}</p>

    {#if !facts}
        <p class="cplugfacts__note" role="status">{t(KIND_KEYS.cplugNoFacts)}</p>
    {:else}
        <p class="cplugfacts__note">{t(KIND_KEYS.cplugContains, { files: facts.files, bytes: facts.bytes, entry: facts.entry })}</p>

        <p class="cplugfacts__label">{t(KIND_KEYS.cplugPermissions)}</p>
        {#if permissions.length}
            <ul class="cplugfacts__list">
                {#each permissions as perm}
                    <li class="cplugfacts__item" class:cplugfacts__item--risk={perm.risk === 'high'}>
                        <span class="cplugfacts__name">{perm.name}</span>
                        <span class="cplugfacts__risk">{perm.risk}</span>
                        {#if perm.reason}<span class="cplugfacts__reason">{perm.reason}</span>{/if}
                    </li>
                {/each}
            </ul>
        {:else}
            <p class="cplugfacts__note">{t(KIND_KEYS.cplugNoPermissions)}</p>
        {/if}

        <p class="cplugfacts__label">{t(KIND_KEYS.cplugTools)}</p>
        {#if tools.length}
            {#each tools as tool}
                <div class="cplugfacts__tool">
                    <p class="cplugfacts__name">{tool.name} <span class="cplugfacts__risk">{tool.gate}</span></p>
                    <p class="cplugfacts__desc">{tool.description}</p>
                    <pre class="cplugfacts__schema">{schemaText(tool.input_schema)}</pre>
                </div>
            {/each}
        {:else}
            <p class="cplugfacts__note">{t(KIND_KEYS.cplugNoTools)}</p>
        {/if}

        {#if hosts.length || lan.length}
            <p class="cplugfacts__label">{t(KIND_KEYS.cplugHosts)}</p>
            <ul class="cplugfacts__list">
                {#each hosts as host}
                    <li class="cplugfacts__item">
                        <span class="cplugfacts__name">{host.host}</span>
                        <span class="cplugfacts__reason">{host.methods.join(' ')} {host.paths.join(' ')}</span>
                        {#if host.reason}<span class="cplugfacts__reason">{host.reason}</span>{/if}
                    </li>
                {/each}
                {#each lan as host}
                    <li class="cplugfacts__item">
                        <span class="cplugfacts__name">{host.entry}</span>
                        <span class="cplugfacts__reason">{host.methods.join(' ')} {host.paths.join(' ')}</span>
                        {#if host.reason}<span class="cplugfacts__reason">{host.reason}</span>{/if}
                    </li>
                {/each}
            </ul>
        {/if}

        {#if secrets.length}
            <p class="cplugfacts__label">{t(KIND_KEYS.cplugSecrets)}</p>
            <ul class="cplugfacts__list">
                {#each secrets as secret}
                    <li class="cplugfacts__item">
                        <span class="cplugfacts__name">{secret.name}</span>
                        <span class="cplugfacts__reason">{secret.label}</span>
                        <span class="cplugfacts__reason">{t(KIND_KEYS.cplugSentTo, { hosts: secret.hosts.join(', ') || '-' })}</span>
                    </li>
                {/each}
            </ul>
        {/if}
    {/if}

    <p class="cplugfacts__note">{t(KIND_KEYS.cplugNotEnabled)}</p>

    <label class="cplugfacts__accept">
        <input type="checkbox" checked={accepted} disabled={busy}
            onchange={(event) => onAccept((event.currentTarget as HTMLInputElement).checked)} />
        <span>{t(KIND_KEYS.cplugTick)}</span>
    </label>
</div>

<style>
    .cplugfacts {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1-5);
        padding: var(--oc-space-2) var(--oc-space-2);
        border: 1px solid var(--oc-yellow);
        border-radius: 4px;
    }

    .cplugfacts__trust {
        margin: 0;
        color: var(--oc-text-primary);
        font-size: var(--oc-fs-body);
        line-height: 1.45;
        border-left: 2px solid var(--oc-coral);
        padding-left: var(--oc-space-2);
    }

    .cplugfacts__label {
        margin: var(--oc-space-0-5) 0 0;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cplugfacts__list {
        margin: 0;
        padding: 0;
        list-style: none;
        max-height: 160px;
        overflow: auto;
    }

    .cplugfacts__item,
    .cplugfacts__name,
    .cplugfacts__desc {
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        line-height: 1.5;
        overflow-wrap: anywhere;
    }

    .cplugfacts__item {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-0-5) var(--oc-space-2);
        color: var(--oc-text-primary);
    }

    .cplugfacts__item--risk .cplugfacts__risk {
        color: var(--oc-coral);
    }

    .cplugfacts__name {
        margin: 0;
        color: var(--oc-text-primary);
    }

    .cplugfacts__risk,
    .cplugfacts__reason {
        color: var(--oc-text-muted);
        font-size: var(--oc-fs-label);
    }

    .cplugfacts__tool {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-0-5);
        padding-top: var(--oc-space-1);
        box-shadow: 0 -1px 0 var(--oc-line-rule);
    }

    .cplugfacts__desc {
        margin: 0;
        color: var(--oc-text-primary);
        white-space: pre-wrap;
    }

    .cplugfacts__schema {
        margin: 0;
        max-height: 120px;
        overflow: auto;
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
        line-height: 1.4;
    }

    .cplugfacts__note {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-label);
        line-height: 1.4;
    }

    .cplugfacts__accept {
        display: flex;
        align-items: flex-start;
        gap: var(--oc-space-2);
        color: var(--oc-text-primary);
        font-size: var(--oc-fs-body);
        line-height: 1.45;
        cursor: pointer;
    }

    .cplugfacts__accept input {
        margin-top: var(--oc-space-0-5);
        flex-shrink: 0;
        width: 16px;
        height: 16px;
    }

    @media (max-width: 767px) {
        .cplugfacts__accept {
            min-height: 44px;
            align-items: center;
        }

        .cplugfacts__accept input {
            margin-top: 0;
            width: 22px;
            height: 22px;
        }
    }
</style>
