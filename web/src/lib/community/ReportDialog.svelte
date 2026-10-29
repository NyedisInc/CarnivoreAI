
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { refusalCodeOf } from '../catalog/install-actions';
    import { GATE_CANCELLED, type RegisterGate } from '../catalog/register-gate.svelte';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import Select from '../base/Select.svelte';
    import { REPORT_REASONS, type CommunityHost, type ReportReason, type ReportTarget } from './community';

    interface Props {
        t: Translate;
        host: CommunityHost;
        target: ReportTarget;
        onclose: () => void;
        gate: RegisterGate;
    }

    const { t, host, target, onclose, gate }: Props = $props();

    let reason = $state<ReportReason>('spam');
    let note = $state('');
    let working = $state(false);
    let done = $state(false);
    let failure = $state<string | null>(null);

    async function send(): Promise<void> {
        working = true;
        failure = null;
        try {
            const base = { kind: target.kind, item_id: target.itemId, reason };
            const extra = target.kind === 'comment' ? { comment_id: target.commentId } : { reviewer: target.reviewRef };
            const sent = await gate.guard(() =>
                host.report({ ...base, ...extra, ...(note.trim() ? { note: note.trim() } : {}) }),
            );
            if (sent === GATE_CANCELLED) failure = t('community.gate.needed');
            else done = true;
        } catch (error) {
            failure = refusalCodeOf(error) === 'unauthorized'
                ? t('community.signed_out')
                : t('community.report.failed');
        } finally {
            working = false;
        }
    }
</script>

<div class="rep" role="group" aria-label={t('community.report.heading')}>
    <p class="rep__heading">{t('community.report.heading')}</p>
    {#if done}
        <p class="rep__note" role="status">{t('community.report.sent')}</p>
        <Button onclick={onclose}>{t('community.close')}</Button>
    {:else}
        <Select label={t('community.report.reason')} bind:value={reason} disabled={working}
            options={REPORT_REASONS.map((value) => ({ value, label: t(`community.report.reason.${value}`) }))} />
        <Field multiline label={t('community.report.note')} rows={2} maxlength={500} disabled={working} bind:value={note} />
        <div class="rep__acts">
            <Button onclick={onclose}>{t('community.cancel')}</Button>
            <Button variant="danger" disabled={working} onclick={() => void send()}>
                {working ? t('community.working') : t('community.report.send')}
            </Button>
        </div>
        {#if failure}
            <p class="rep__note rep__note--out" role="status">{failure}</p>
        {/if}
    {/if}
</div>

<style>
    .rep {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 8px 10px;
        border: 1px solid var(--cat-line);
        border-radius: 3px;
        background: var(--cat-raised);
    }
    .rep__heading {
        margin: 0;
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .rep__acts { display: flex; gap: 6px; }
    .rep__note { margin: 0; color: var(--cat-muted); font-size: 11px; line-height: 1.45; }
    .rep__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-panel);
        color: var(--cat-text);
    }
</style>
