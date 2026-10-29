
<script lang="ts">
    import { ledStateFor } from './led';
    import { ledAttrsForStatus, normalizeStatus, STATUS_DOT_CLASS, statusTitle } from './status-dot';

    interface Props {
        status?: string | null;
        unread?: boolean;
        startupGate?: string | null;
        statusSource?: string | null;
        /* there is nothing */
        activityHint?: string | null;
        parkedSummary?: string | null;
        transport?: string | null;
        hostOffline?: string | null;
        usageLimit?: string | null;
        size?: string | null;
        showLabel?: boolean;
        bare?: boolean;
    }

    let {
        status = null,
        unread = false,
        startupGate = null,
        statusSource = null,
        activityHint = null,
        parkedSummary = null,
        transport = null,
        hostOffline = null,
        usageLimit = null,
        size = null,
        showLabel = false,
        bare = false,
    }: Props = $props();

    const key = $derived(normalizeStatus(status));
    const led = $derived(
        ledStateFor({
            activity_status: key,
            unread,
            startup_gate: startupGate,
            transport,
            host_offline: hostOffline,
            usage_limit: usageLimit,
        }),
    );
    const label = $derived(statusTitle(key, statusSource, activityHint, unread, parkedSummary, hostOffline, usageLimit));
    const dotClass = $derived(STATUS_DOT_CLASS[key] ?? 'unknown');
    const sizeVar = $derived(
        typeof size === 'string' && /^[0-9]+(\.[0-9]+)?(px|rem|em)$/.test(size)
            ? `--led-size: ${size}`
            : null,
    );
    const bareAttrs = $derived(bare
        ? ledAttrsForStatus(status, {
            unread,
            startup_gate: startupGate,
            status_source: statusSource,
            activity_hint: activityHint,
            parked_summary: parkedSummary,
            transport,
            host_offline: hostOffline,
            usage_limit: usageLimit,
        })
        : null);
</script>

{#if bareAttrs}<span {...bareAttrs}></span>{:else}
<span class="tw:inline-flex tw:items-center tw:gap-1.5 tw:align-middle">
    <span
        class="status-dot status-dot--{dotClass} status-led"
        data-inner={led.inner}
        data-outer={led.outer}
        role="img"
        title={label}
        aria-label={label}
        style={sizeVar}
    ></span>
    {#if showLabel}
        <span class="tw:text-xs tw:leading-none tw:opacity-70">{label}</span>
    {/if}
</span>
{/if}
