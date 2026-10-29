
<script lang="ts">
    import { t } from '../../lib/i18n/index.svelte';
    import { asleep, recent, sessions, wakeOrPick } from '../api';
    import { authFetch } from '../api/auth.svelte';
    import type { LayoutMember } from './api';
    import { displayName } from './names';
    import { memberRestartRequest } from './member-restart';

    let { member, instance = '' }: { member: LayoutMember | null; instance?: string } = $props();

    const sleeping = $derived(
        (asleep.data ?? []).find((rec) => rec.id === member?.session_row_id && rec.asleep !== false) ?? null,
    );
    const record = $derived(
        sleeping ?? (recent.data?.sessions ?? []).find((rec) => rec.session_uuid === member?.session_uuid) ?? null,
    );
    const uuid = $derived(member?.session_uuid ?? sleeping?.session_uuid ?? '');
    const name = $derived(displayName(record?.title, record?.tmux_name) || instance);
    const downAs = $derived<'asleep' | 'dead' | 'gone'>(sleeping ? 'asleep' : uuid ? 'dead' : 'gone');

    let busy = $state(false);
    let error = $state('');

    async function wake(): Promise<void> {
        if (busy || !uuid) return;
        busy = true;
        error = '';
        try {
            const answer = await wakeOrPick(uuid, record?.tmux_name ?? '', name);
            if (answer && answer.status !== 'started') {
                error = t('layout.member.asleep.wake_failed', { name, reason: answer.detail });
            }
        } catch (failure) {
            error = t('layout.member.asleep.wake_failed', { name, reason: (failure as Error).message });
        }
        await Promise.all([asleep.refresh(true), sessions.refresh(true)]);
        busy = false;
    }

    interface Picker {
        open(tmuxName: string, label: string, status: string | null, uuid: string | null): Promise<
            { agentType: string | null; mode: string; sessionUuid?: string; confirmRestartLive?: boolean } | null
        >;
        lastError(): string;
    }

    async function recreate(): Promise<void> {
        if (busy || !uuid) return;
        const picker = (globalThis as { SessionRestartPicker?: Picker }).SessionRestartPicker;
        if (!picker) {
            error = t('layout.member.dead.recreate_failed', { name, reason: 'the restart picker did not load' });
            return;
        }
        busy = true;
        error = '';
        try {
            const choice = await picker.open(record?.tmux_name ?? '', name, 'dead', uuid);
            if (!choice) {
                const why = picker.lastError();
                if (why) error = t('layout.member.dead.recreate_failed', { name, reason: why });
                return;
            }
            const req = memberRestartRequest(choice, uuid, record?.tmux_name ?? '');
            const answer = await authFetch<{ status?: string; ok?: boolean; detail?: string }>(req.path, {
                method: 'POST',
                body: JSON.stringify(req.body),
            });
            const worked = req.kind === 'recreate' ? answer.status === 'started' : answer.ok === true;
            if (!worked) {
                error = t('layout.member.dead.recreate_failed', { name, reason: answer.detail ?? '' });
            }
            await sessions.refresh(true);
        } catch (failure) {
            error = t('layout.member.dead.recreate_failed', { name, reason: (failure as Error).message });
        } finally {
            busy = false;
        }
    }
</script>

<div class="lmd" data-layout-member-down={downAs} data-layout-member={instance || uuid}>
    {#if downAs === 'asleep'}
        <p class="lmd-title">{t('layout.member.asleep.title')}</p>
        <p class="lmd-body">{t('layout.member.asleep.body', { name })}</p>
        <button class="modal-btn modal-btn-confirm" data-member-action="wake" disabled={busy} onclick={() => void wake()}
            >{busy ? t('layout.member.asleep.waking') : t('layout.member.asleep.wake')}</button
        >
    {:else if downAs === 'dead'}
        <p class="lmd-title">{t('layout.member.dead.title')}</p>
        <p class="lmd-body">{t('layout.member.dead.body', { name })}</p>
        <button class="modal-btn modal-btn-confirm" data-member-action="recreate" disabled={busy} onclick={() => void recreate()}
            >{busy ? t('layout.member.dead.recreating') : t('layout.member.dead.recreate')}</button
        >
    {:else}
        <p class="lmd-title">{t('layout.member.gone.title')}</p>
        <p class="lmd-body">{t('layout.member.gone.body')}</p>
    {/if}
    {#if error}
        <p class="lmd-error" role="alert">{error}</p>
    {/if}
</div>

<style>
  @layer components {
      .lmd {
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          gap: var(--oc-space-2);
          padding: var(--oc-space-3);
          font-family: var(--font-mono);
      }

      .lmd-title {
          margin: 0;
          font-size: var(--oc-fs-micro, var(--oc-fs-micro));
          letter-spacing: var(--oc-tracking-label, 0.6px);
          text-transform: uppercase;
          color: var(--oc-text-muted);
      }

      .lmd-body {
          margin: 0;
          color: var(--oc-text-dim);
          font-size: var(--oc-fs-label);
      }

      .lmd-error {
          margin: 0;
          padding: 6px var(--oc-space-2);
          border-left: 2px solid var(--oc-coral);
          background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-raised));
          color: var(--oc-text-primary);
          font-size: var(--oc-fs-body);
      }
  }
</style>
