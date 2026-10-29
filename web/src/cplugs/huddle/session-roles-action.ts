import type { Contribution } from '../sdk';
import { t } from '../sdk';
import type { SessionCardRow } from '../../lib/plugins/types';
import { swarmRoster } from './agents/agent-roster.svelte';
import { sessionLeads, setProjectLead } from './task-manager-session-prefs';

export const LEAD_ACTION_ID = 'huddle-project-lead';

export function isSwarmBody(row: SessionCardRow): boolean {
  const id = row.sessionId;
  return !!id && swarmRoster.agents.some((agent) => agent.session_id === id);
}

function leadHidden(row: SessionCardRow): boolean {
  return isSwarmBody(row) || row.projectId == null;
}

async function attempt(what: string, write: () => Promise<unknown>, refresh: () => void | Promise<void>): Promise<void> {
  try {
    await write();
  } catch (err) {
    console.error(`[huddle] ${what} failed:`, err);
    return;
  }
  await refresh();
}

const lead: Contribution<'session-card-action'> = {
  id: LEAD_ACTION_ID,
  surface: 'session-card-action',
  order: 520,
  enabled: () => true,
  payload: {
    shortcut: 'P',
    label: (row) => t(sessionLeads(row.sessionUuid ?? '', row.projectId) ? 'cplug.huddle.role.lead_off' : 'cplug.huddle.role.lead_on'),
    hidden: leadHidden,
    async run(row, context): Promise<void> {
      const uuid = row.sessionUuid;
      if (!uuid || row.projectId == null) return;
      const leading = sessionLeads(uuid, row.projectId);
      await attempt('project lead', () => setProjectLead(row.projectId as number | string, leading ? null : uuid), context.refresh);
    },
  },
};

export const roleActions: Contribution<'session-card-action'>[] = [lead];
