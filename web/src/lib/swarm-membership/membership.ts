import { refreshSwarmRoster } from '../../cplugs/sdk/swarm-roster.svelte';
import { authFetch } from '../../opscenter/api/auth.svelte';
import { confirmOk } from '../confirm-ok/confirm-ok';
import { t } from '../i18n/index.svelte';
import { announceFailure } from '../sidebar-shell/interaction-globals';

interface Refusal {
    code: string;
    sentence: string;
}

export function refusalOf(err: unknown): Refusal | null {
    const payload = (err as { payload?: unknown } | null)?.payload as Record<string, unknown> | null | undefined;
    const body = (payload && typeof payload.detail === 'object' && payload.detail !== null ? payload.detail : payload) as Record<string, unknown> | null | undefined;
    if (!body || typeof body.code !== 'string') return null;
    const sentence = typeof body.sentence === 'string' ? body.sentence : typeof body.message === 'string' ? body.message : '';
    return { code: body.code, sentence };
}

interface Accepted {
    confirm_restart: boolean;
    create_project_agent: boolean;
}

function say(message: string, joining: boolean): void {
    announceFailure(t(joining ? 'swarm.membership.join_failed' : 'swarm.membership.leave_failed', { reason: message }));
}

async function withAcceptance(call: (accepted: Accepted) => Promise<unknown>, joining: boolean): Promise<boolean> {
    const accepted: Accepted = { confirm_restart: false, create_project_agent: false };
    for (let round = 0; round < 3; round += 1) {
        try {
            await call(accepted);
            void refreshSwarmRoster();
            return true;
        } catch (err) {
            const refusal = refusalOf(err);
            if (refusal?.code === 'no_project_agent' && !accepted.create_project_agent) {
                const ok = await confirmOk({ title: t('swarm.membership.no_agent_title'), message: refusal.sentence || t('swarm.membership.no_agent_fallback') });
                if (!ok) return false;
                accepted.create_project_agent = true;
                continue;
            }
            if (refusal?.code === 'restart_needed' && !accepted.confirm_restart) {
                const ok = await confirmOk({
                    title: t(joining ? 'swarm.membership.join_title' : 'swarm.membership.leave_title'),
                    message: refusal.sentence || t(joining ? 'swarm.membership.join_fallback' : 'swarm.membership.leave_fallback'),
                    okLabel: t(joining ? 'swarm.membership.join_ok' : 'swarm.membership.leave_ok'),
                });
                if (!ok) return false;
                accepted.confirm_restart = true;
                continue;
            }
            say(refusal?.sentence || (err instanceof Error ? err.message : String(err)), joining);
            return false;
        }
    }
    return false;
}

export function joinSwarm(sessionUuid: string): Promise<boolean> {
    return withAcceptance((a) => authFetch('/swarm/members', { method: 'POST', body: JSON.stringify({ session_uuid: sessionUuid, ...a }) }), true);
}

export function leaveSwarm(sessionUuid: string): Promise<boolean> {
    return withAcceptance(
        (a) => authFetch(`/swarm/members/${encodeURIComponent(sessionUuid)}${a.confirm_restart ? '?confirm_restart=true' : ''}`, {
            method: 'DELETE', body: JSON.stringify({ confirm_restart: a.confirm_restart }),
        }),
        false,
    );
}
