
<script lang="ts">
    import { KIND_KEYS } from '../../../../client/js/labels/catalog-kind.js';
    import Checkbox from '../base/Checkbox.svelte';
    import Tag from '../base/Tag.svelte';
    import type { Translate } from '../sessions/types';
    import type { CplugFactsData } from './types';

    interface Props {
        facts: CplugFactsData | null;
        accepted: boolean;
        busy: boolean;
        isUpdate?: boolean;
        t: Translate;
        onAccept: (next: boolean) => void;
    }

    const { facts, accepted, busy, isUpdate = false, t, onAccept }: Props = $props();

    const permissions = $derived(facts?.permissions ?? []);
    const tools = $derived(facts?.tools ?? []);
    const hosts = $derived(facts?.network_hosts ?? []);
    const lan = $derived(facts?.lan_hosts ?? []);
    const secrets = $derived(facts?.secrets ?? []);
    const hasEntry = $derived(Boolean(facts?.entry && facts.entry.trim()));

    function schemaText(schema: unknown): string {
        try {
            return JSON.stringify(schema ?? {}, null, 2);
        } catch {
            return '{}';
        }
    }

    function riskTone(risk: string | undefined): 'danger' | 'warn' | 'info' {
        if (risk === 'high' || risk === 'never') return 'danger';
        if (risk === 'medium') return 'warn';
        return 'info';
    }
</script>

<div class="cplugfacts" data-cplug-facts>
    <p class="cplugfacts__trust" role="note">{t(KIND_KEYS.cplugTrust)}</p>

    {#if !facts}
        <p class="cplugfacts__note" role="status">{t(KIND_KEYS.cplugNoFacts)}</p>
    {:else}
        {#if hasEntry}
            <p class="cplugfacts__meta">{t(KIND_KEYS.cplugContains, { files: facts.files, bytes: facts.bytes, entry: facts.entry })}</p>
        {/if}

        <div class="cplugfacts__section">
            <p class="cplugfacts__label">{t(KIND_KEYS.cplugPermissions)}</p>
            {#if permissions.length}
                <ul class="cplugfacts__list">
                    {#each permissions as perm}
                        <li class="cplugfacts__item" class:cplugfacts__item--risk={perm.risk === 'high'}>
                            <div class="cplugfacts__item-head">
                                <span class="cplugfacts__name">{perm.name}</span>
                                <Tag tone={riskTone(perm.risk)}>{perm.risk}</Tag>
                            </div>
                            {#if perm.reason}<span class="cplugfacts__reason">{perm.reason}</span>{/if}
                        </li>
                    {/each}
                </ul>
            {:else}
                <div class="cplugfacts__empty"><Tag tone="ok">{t(KIND_KEYS.cplugNoPermissions)}</Tag></div>
            {/if}
        </div>

        <div class="cplugfacts__section">
            <p class="cplugfacts__label">{t(KIND_KEYS.cplugTools)}</p>
            {#if tools.length}
                {#each tools as tool}
                    <div class="cplugfacts__tool">
                        <div class="cplugfacts__item-head">
                            <span class="cplugfacts__name">{tool.name}</span>
                            {#if tool.gate}<Tag tone="warn">{tool.gate}</Tag>{/if}
                        </div>
                        <p class="cplugfacts__desc">{tool.description}</p>
                        <pre class="cplugfacts__schema">{schemaText(tool.input_schema)}</pre>
                    </div>
                {/each}
            {:else}
                <div class="cplugfacts__empty"><Tag tone="ok">{t(KIND_KEYS.cplugNoTools)}</Tag></div>
            {/if}
        </div>

        {#if hosts.length || lan.length}
            <div class="cplugfacts__section">
                <p class="cplugfacts__label">{t(KIND_KEYS.cplugHosts)}</p>
                <ul class="cplugfacts__list">
                    {#each hosts as host}
                        <li class="cplugfacts__item">
                            <div class="cplugfacts__item-head">
                                <span class="cplugfacts__name">{host.host}</span>
                                <Tag tone="info">{host.methods.join(' ')} {host.paths.join(' ')}</Tag>
                            </div>
                            {#if host.reason}<span class="cplugfacts__reason">{host.reason}</span>{/if}
                        </li>
                    {/each}
                    {#each lan as host}
                        <li class="cplugfacts__item">
                            <div class="cplugfacts__item-head">
                                <span class="cplugfacts__name">{host.entry}</span>
                                <Tag tone="warn">{host.methods.join(' ')} {host.paths.join(' ')}</Tag>
                            </div>
                            {#if host.reason}<span class="cplugfacts__reason">{host.reason}</span>{/if}
                        </li>
                    {/each}
                </ul>
            </div>
        {/if}

        {#if secrets.length}
            <div class="cplugfacts__section">
                <p class="cplugfacts__label">{t(KIND_KEYS.cplugSecrets)}</p>
                <ul class="cplugfacts__list">
                    {#each secrets as secret}
                        <li class="cplugfacts__item">
                            <div class="cplugfacts__item-head">
                                <span class="cplugfacts__name">{secret.name}</span>
                                <Tag tone="warn">{secret.label}</Tag>
                            </div>
                            <span class="cplugfacts__reason">{t(KIND_KEYS.cplugSentTo, { hosts: secret.hosts.join(', ') || '-' })}</span>
                        </li>
                    {/each}
                </ul>
            </div>
        {/if}
    {/if}

    {#if !isUpdate}
        <p class="cplugfacts__note">{t(KIND_KEYS.cplugNotEnabled)}</p>
    {/if}

    <div class="cplugfacts__ack">
        <Checkbox
            tone="danger"
            checked={accepted}
            disabled={busy}
            label={t(KIND_KEYS.cplugTick)}
            onchange={(event) => onAccept((event.currentTarget as HTMLInputElement).checked)}
        />
    </div>
</div>

<style>
  @layer components {
    .cplugfacts {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        padding: var(--oc-space-3);
        border: var(--oc-border) solid color-mix(in srgb, var(--oc-yellow) 65%, var(--oc-line-panel));
        border-radius: var(--oc-radius-panel);
        background: color-mix(in srgb, var(--oc-yellow) 7%, var(--oc-ground-field));
        color: var(--oc-text-primary);
    }

    .cplugfacts__trust {
        margin: 0;
        color: var(--oc-text-bright);
        font-size: var(--oc-fs-body);
        line-height: var(--oc-lh-body);
        border-left: var(--oc-border) solid var(--oc-coral);
        padding-left: var(--oc-space-2);
    }

    .cplugfacts__meta {
        margin: 0;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
    }

    .cplugfacts__section {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1);
        padding-top: var(--oc-space-1-5);
        border-top: var(--oc-border) solid var(--oc-line-faint);
    }

    .cplugfacts__label {
        margin: 0;
        color: var(--oc-yellow);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
        text-transform: uppercase;
        letter-spacing: var(--oc-tracking-label);
    }

    .cplugfacts__list {
        margin: 0;
        padding: 0;
        list-style: none;
        max-height: 180px;
        overflow: auto;
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1-5);
    }

    .cplugfacts__item,
    .cplugfacts__tool {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1);
        padding: var(--oc-space-1-5) var(--oc-space-2);
        border: var(--oc-border) solid var(--oc-line-rule);
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-raised);
    }

    .cplugfacts__item--risk {
        border-color: color-mix(in srgb, var(--oc-coral) 55%, var(--oc-line-rule));
    }

    .cplugfacts__item-head {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: var(--oc-space-1-5);
    }

    .cplugfacts__name {
        margin: 0;
        color: var(--oc-text-bright);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        overflow-wrap: anywhere;
    }

    .cplugfacts__reason {
        color: var(--oc-text-primary);
        font-size: var(--oc-fs-label);
        line-height: var(--oc-lh-body);
        overflow-wrap: anywhere;
    }

    .cplugfacts__desc {
        margin: 0;
        color: var(--oc-text-primary);
        font-size: var(--oc-fs-label);
        line-height: var(--oc-lh-body);
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }

    .cplugfacts__schema {
        margin: 0;
        padding: var(--oc-space-1-5);
        max-height: 120px;
        overflow: auto;
        border: var(--oc-border) solid var(--oc-line-faint);
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-field);
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
        line-height: var(--oc-lh-body);
    }

    .cplugfacts__empty {
        display: flex;
        align-items: center;
    }

    .cplugfacts__note {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-label);
        line-height: var(--oc-lh-body);
    }

    .cplugfacts__ack {
        padding-top: var(--oc-space-2);
        border-top: var(--oc-border) solid var(--oc-line-faint);
    }
  }
</style>
