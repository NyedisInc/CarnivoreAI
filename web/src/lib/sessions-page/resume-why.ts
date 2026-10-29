import type { HistorySession } from '../projects-shared/history-api';

export function resumeWhyKey(session: HistorySession): string {
    if (session.state === 'running') return 'projects.page.resume.why_running';
    if (session.state === 'asleep') return 'projects.page.resume.why_asleep';
    if (session.has_transcript) return 'projects.page.resume.why_disk';
    if (!session.claude_session_uuid) return 'projects.page.resume.why_fresh';
    return 'projects.page.resume.why_gone';
}
