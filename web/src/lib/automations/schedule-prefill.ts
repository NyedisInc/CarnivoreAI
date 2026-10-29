import type { AutomationTarget, ProjectChoice, SessionChoice } from './api';

export type SchedulePrefill = { kind: 'session'; id: string } | { kind: 'project'; id: number };

const PAGE = '#automations';

const SESSION_RE = /^#automations\/new\/session\/([0-9A-Za-z][0-9A-Za-z-]{0,63})$/;
const PROJECT_RE = /^#automations\/new\/project\/([0-9]{1,18})$/;

export function scheduleHash(prefill: SchedulePrefill): string {
  return `${PAGE}/new/${prefill.kind}/${prefill.id}`;
}

export function parsePrefill(hash: string | null | undefined): SchedulePrefill | null {
  if (typeof hash !== 'string') return null;
  const session = SESSION_RE.exec(hash);
  if (session?.[1]) return { kind: 'session', id: session[1] };
  const project = PROJECT_RE.exec(hash);
  return project?.[1] ? { kind: 'project', id: Number(project[1]) } : null;
}

export interface EditorStart {
  target: AutomationTarget | null;
  projectId: number | null;
  name: string;
}

export function editorStart(
  prefill: SchedulePrefill,
  blank: AutomationTarget | null,
  sessions: readonly SessionChoice[],
  projects: readonly ProjectChoice[],
): EditorStart {
  if (prefill.kind === 'project') {
    const target = blank && 'project_id' in blank ? { ...blank, project_id: prefill.id } : blank;
    return { target, projectId: prefill.id, name: '' };
  }
  const found = sessions.find((s) => s.session_uuid === prefill.id);
  const projectId = found?.project_id ?? null;
  const known = projectId !== null && projects.some((p) => p.id === projectId);
  const label = found?.name ?? found?.tmux_name ?? '';
  const target: AutomationTarget = {
    kind: 'session_message',
    session_uuid: prefill.id,
    session_name: label,
    text: '',
    if_asleep: 'wake',
    if_gone: 'start',
    project_id: known ? projectId : null,
  };
  return { target, projectId: known ? projectId : null, name: '' };
}

interface ScheduleHost {
  location: { hash: string };
  CloudeWeb?: { openAutomationsScreen?: () => boolean };
}

export function openScheduleThis(prefill: SchedulePrefill, host: ScheduleHost | null = typeof window !== 'undefined' ? (window as unknown as ScheduleHost) : null): boolean {
  if (!host) return false;
  host.location.hash = scheduleHash(prefill);
  return host.CloudeWeb?.openAutomationsScreen?.() ?? false;
}

const EDIT_RE = /^#automations\/edit\/([0-9A-Za-z][0-9A-Za-z_-]{0,63})$/;

export function parseEditId(hash: string | null | undefined): string | null {
  return typeof hash === 'string' ? (EDIT_RE.exec(hash)?.[1] ?? null) : null;
}

export function openAutomationEdit(automationId: string, host: ScheduleHost | null = typeof window !== 'undefined' ? (window as unknown as ScheduleHost) : null): boolean {
  if (!host) return false;
  host.location.hash = `${PAGE}/edit/${automationId}`;
  return host.CloudeWeb?.openAutomationsScreen?.() ?? false;
}

const SESSION_FOCUS_RE = /^#automations\/session\/([0-9A-Za-z][0-9A-Za-z-]{0,63})$/;

export function parseSessionFocus(hash: string | null | undefined): string | null {
  return typeof hash === 'string' ? (SESSION_FOCUS_RE.exec(hash)?.[1] ?? null) : null;
}

export function openSessionAutomations(sessionUuid: string, host: ScheduleHost | null = typeof window !== 'undefined' ? (window as unknown as ScheduleHost) : null): boolean {
  if (!host) return false;
  host.location.hash = `${PAGE}/session/${sessionUuid}`;
  return host.CloudeWeb?.openAutomationsScreen?.() ?? false;
}

export const SESSIONS_TAB_HASH = `${PAGE}/sessions`;
export const ADVANCED_TAB_HASH = `${PAGE}/advanced`;

export function isSessionsTabHash(hash: string | null | undefined): boolean {
  return hash === SESSIONS_TAB_HASH;
}

export function isAdvancedTabHash(hash: string | null | undefined): boolean {
  return hash === ADVANCED_TAB_HASH;
}

const RUN_LINK_RE = /^#automations\/run\/([\w-]+)$/;

export function parseRunLink(hash: string | null | undefined): string | null {
  return typeof hash === 'string' ? (RUN_LINK_RE.exec(hash)?.[1] ?? null) : null;
}

const FEED_RUN_RE = /^#automations\/sessions\/run\/([\w-]+)$/;

export function parseFeedRun(hash: string | null | undefined): string | null {
  return typeof hash === 'string' ? (FEED_RUN_RE.exec(hash)?.[1] ?? null) : null;
}
