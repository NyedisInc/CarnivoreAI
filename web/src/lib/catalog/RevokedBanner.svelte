
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import Button from '../base/Button.svelte';
    import Tag from '../base/Tag.svelte';
    import type { Translate } from '../sessions/types';

    interface Props {
        reason?: string | null;
        since?: string | null;
        onDisableUninstall?: () => void;
        busy?: boolean;
        t: Translate;
    }

    const { reason = null, since = null, onDisableUninstall, busy = false, t }: Props = $props();
</script>

<div class="revoked-banner" role="alert" data-revoked-banner>
    <div class="revoked-banner__head">
        <Tag tone="danger" data-revoked-tag>{t(SKILL_KEYS.revokedBadge)}</Tag>
        <p class="revoked-banner__notice">{t(SKILL_KEYS.revokedNotice)}</p>
    </div>
    {#if reason}
        <p class="revoked-banner__reason" data-revoked-reason>{t(SKILL_KEYS.revokedDetail, { reason })}</p>
    {/if}
    {#if since}
        <p class="revoked-banner__since" data-revoked-since>{since}</p>
    {/if}
    {#if onDisableUninstall}
        <div class="revoked-banner__act">
            <Button
                variant="danger"
                size="sm"
                disabled={busy}
                data-act="disable-uninstall"
                onclick={onDisableUninstall}
            >
                {t(SKILL_KEYS.revokedDisableUninstall)}
            </Button>
        </div>
    {/if}
</div>

<style>
  @layer components {
    .revoked-banner {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1-5);
        padding: var(--oc-space-2) var(--oc-space-3);
        border: var(--oc-border) solid var(--oc-coral);
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
    }

    .revoked-banner__head {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--oc-space-2);
    }

    .revoked-banner__notice,
    .revoked-banner__reason,
    .revoked-banner__since {
        margin: 0;
        font-size: var(--oc-fs-body);
        line-height: var(--oc-lh-body);
    }

    .revoked-banner__reason,
    .revoked-banner__since {
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-micro);
    }

    .revoked-banner__act {
        display: flex;
        align-items: center;
        padding-top: var(--oc-space-1);
    }
  }
</style>
