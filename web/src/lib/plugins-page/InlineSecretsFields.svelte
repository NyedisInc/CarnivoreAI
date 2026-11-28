
<script lang="ts">
    import Field from '../base/Field.svelte';
    import Tag from '../base/Tag.svelte';
    import type { CplugSecretStatus } from './cplugs-adapter';
    import type { SecretDescriptor } from './install-sheet-model';
    import type { Translate } from '../sessions/types';

    interface Props {
        secrets: readonly SecretDescriptor[];
        values?: Record<string, string>;
        secretsStatus?: Readonly<Record<string, CplugSecretStatus>>;
        busy?: boolean;
        onChange?: (name: string, value: string) => void;
        t: Translate;
    }

    let {
        secrets,
        values = $bindable({}),
        secretsStatus,
        busy = false,
        onChange,
        t,
    }: Props = $props();

    function updateSecret(name: string, nextValue: string): void {
        values = { ...values, [name]: nextValue };
        onChange?.(name, nextValue);
    }

    function hostsCaption(hosts: readonly string[]): string {
        if (!hosts || hosts.length === 0) return t('plugins.page.install_sheet.secret_hosts_none');
        return t('plugins.page.install_sheet.secret_hosts', { hosts: hosts.join(', ') });
    }
</script>

{#if secrets.length > 0}
    <section class="pl-secrets" data-inline-secrets aria-label={t('plugins.page.install_sheet.secrets_heading')}>
        <h3 class="pl-secrets__head">{t('plugins.page.install_sheet.secrets_heading')}</h3>
        <div class="pl-secrets__list">
            {#each secrets as secret, i (`sec:${i}`)}
                {@const status = secretsStatus?.[secret.name]}
                {@const present = status?.present === true || status?.secret_present === true}
                {@const needsReentry = status?.needs_reentry === true}
                <div class="pl-secrets__row" data-secret-row={secret.name}>
                    <div class="pl-secrets__top">
                        <span class="pl-secrets__name">{secret.name}</span>
                        {#if needsReentry}
                            <Tag tone="warn" data-secret-status="needs_reentry">
                                {t('plugins.page.install_sheet.secret_needs_reentry')}
                            </Tag>
                        {:else if present}
                            <Tag tone="ok" data-secret-status="present">
                                {t('plugins.page.install_sheet.secret_present')}
                            </Tag>
                        {/if}
                    </div>
                    <Field
                        type="password"
                        autocomplete="new-password"
                        label={secret.label || secret.name}
                        help={hostsCaption(secret.hosts)}
                        value={values[secret.name] ?? ''}
                        disabled={busy}
                        data-secret-input={secret.name}
                        oninput={(e) => updateSecret(secret.name, e.currentTarget.value)}
                    />
                </div>
            {/each}
        </div>
    </section>
{/if}

<style>
    @layer components {
        .pl-secrets {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
            padding: var(--oc-space-2);
            border: var(--oc-border) solid var(--oc-line-surface);
            border-radius: var(--oc-radius-panel);
            background: var(--oc-surface-raised);
        }

        .pl-secrets__head {
            margin: 0;
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-caps);
            text-transform: uppercase;
        }

        .pl-secrets__list {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
        }

        .pl-secrets__row {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1);
        }

        .pl-secrets__top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
        }

        .pl-secrets__name {
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
        }
    }
</style>
