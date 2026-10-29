export interface PickerChoice {
    agentType: string | null;
    mode: string;
    sessionUuid?: string;
    confirmRestartLive?: boolean;
}

export function memberRestartRequest(
    choice: PickerChoice,
    uuid: string,
    tmuxName: string,
): { path: string; body: Record<string, unknown>; kind: 'recreate' | 'restart' } {
    if (choice.mode === 'recreate') {
        return {
            path: '/sessions/recreate',
            body: { session_uuid: choice.sessionUuid ?? uuid, agent_type: choice.agentType },
            kind: 'recreate',
        };
    }
    const body: Record<string, unknown> = { session_name: tmuxName };
    if (choice.agentType) body.agent_type = choice.agentType;
    if (choice.confirmRestartLive === true) body.confirm_restart_live = true;
    return { path: '/sessions/respawn', body, kind: 'restart' };
}
