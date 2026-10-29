import { ledStateFor } from '../led';
import type { MemberState } from '../../cplugs/sdk/swarm-face.svelte';
import type { SwarmRosterAgent } from '../../cplugs/sdk/swarm-roster.svelte';

export interface MemberSignals {
    status: string | null | undefined;
    unread?: boolean | null;
    startupGate?: string | null;
    transport?: string | null;
    hostOffline?: string | null;
    usageLimit?: string | null;
}

export interface MemberFace {
    state: MemberState;
    unread: boolean;
}

export function memberState(s: MemberSignals): MemberFace {
    const status = s.status ?? null;
    const led = ledStateFor({
        activity_status: status ?? undefined,
        unread: !!s.unread,
        startup_gate: s.startupGate ?? null,
        transport: s.transport ?? null,
        host_offline: s.hostOffline ?? null,
        usage_limit: s.usageLimit ?? null,
    } as Parameters<typeof ledStateFor>[0]);
    switch (led.inner) {
        case 'asleep': return { state: 'asleep', unread: false };
        case 'asleep-unread': return { state: 'asleep', unread: true };
        case 'disconnected': return { state: 'unknown', unread: false };
        case 'dead': return { state: 'dead', unread: false };
        case 'limit': return { state: 'alert_immediate', unread: false };
        case 'waiting-input': return { state: 'startup_gate', unread: false };
        case 'waiting-permission': return { state: 'question', unread: false };
        case 'notice': return { state: 'notice', unread: false };
        case 'working': return { state: status === 'working_subagent' ? 'working_subagent' : 'working', unread: false };
        case 'done': return { state: 'finished_unread', unread: false };
        case 'idle': return { state: 'idle', unread: false };
        default: return { state: 'unknown', unread: false };
    }
}

export interface Membership {
    agentId: number;
    rank: string;
    seed: number;
}

export function memberOf(row: Record<string, unknown>, roster: readonly SwarmRosterAgent[]): Membership | null {
    const uuid = typeof row.session_uuid === 'string' ? row.session_uuid
        : typeof (row.session as { session_uuid?: unknown } | undefined)?.session_uuid === 'string'
            ? (row.session as { session_uuid: string }).session_uuid : '';
    const listed = typeof row.swarm_agent_id === 'number' ? row.swarm_agent_id : null;
    const agent = roster.find((a) => a.state !== 'torn_down' && (listed !== null ? a.id === listed : !!uuid && a.session_uuid === uuid));
    if (listed === null && !agent) return null;
    const id = listed ?? agent!.id;
    const rank = typeof row.swarm_rank === 'string' && row.swarm_rank ? row.swarm_rank : (agent?.rank ?? 'feature');
    const seed = typeof row.swarm_character_seed === 'number' ? row.swarm_character_seed : (agent?.character_seed ?? id);
    return { agentId: id, rank, seed };
}
