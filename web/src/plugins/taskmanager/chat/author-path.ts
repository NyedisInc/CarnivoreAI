import type { AuthorCrumb } from './chat-api';

export interface CrumbIcon {
  set: 'glyph' | 'icon';
  name: string;
}

export const CRUMB_ICON: Readonly<Record<AuthorCrumb['kind'], CrumbIcon>> = {
  company: { set: 'glyph', name: 'building' },
  project: { set: 'glyph', name: 'folder' },
  agent: { set: 'icon', name: 'bot' },
  sysop: { set: 'glyph', name: 'crown' },
  owner: { set: 'icon', name: 'person' },
};

export function crumbLabel(crumb: AuthorCrumb, you: string): string {
  return crumb.kind === 'owner' ? you : crumb.name;
}

export function crumbLinks(crumb: AuthorCrumb): boolean {
  return crumb.kind !== 'owner' && typeof crumb.agent_id === 'number' && crumb.agent_id > 0;
}

export function crumbIcon(crumb: AuthorCrumb): CrumbIcon {
  return CRUMB_ICON[crumb.kind] ?? CRUMB_ICON.agent;
}
