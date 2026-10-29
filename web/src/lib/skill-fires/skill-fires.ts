import { authFetch } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';
import { durationText } from '../timers/timers';

export type SkillsState = 'measured' | 'not_measured' | 'unsupported';

export interface SkillFire {
    skill: string;
    at: string | null;
    source: 'tool_use' | 'slash' | 'inferred';
    harness: string;
    profile: string;
}

export interface SessionSkillFires {
    state: SkillsState;
    fired: number | null;
    recent: SkillFire[];
}

export function fetchSkillFires(sessionId: string): Promise<SessionSkillFires> {
    return authFetch<SessionSkillFires>(`/sessions/${encodeURIComponent(sessionId)}/skill-fires`);
}

export function agoText(iso: string | null | undefined, nowMs: number): string | null {
    if (!iso) return null;
    const at = Date.parse(iso);
    if (!Number.isFinite(at)) return null;
    return t('skills.list.ago', { time: durationText(Math.max(0, (nowMs - at) / 1000)) });
}

export function emptyMessage(payload: SessionSkillFires): string | null {
    if (payload.state === 'unsupported') return t('skills.list.unsupported');
    if (payload.state === 'not_measured') return t('skills.list.not_measured');
    if (payload.recent.length === 0) return t('skills.list.empty');
    return null;
}
