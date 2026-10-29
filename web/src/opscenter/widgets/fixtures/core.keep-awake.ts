import { projectList, sessionList } from './made-up';
import type { WidgetFixtures } from './types';

const SETTINGS = {
  enabled: true,
  idle_minutes: 30,
  min_idle_minutes: 5,
  max_idle_minutes: 240,
  unread_blocks_sleep: true,
  unread_idle_minutes: 60,
};

export const keepAwakeFixtures: WidgetFixtures = {
  data: {
    'GET /auto-sleep': {
      ...SETTINGS,
      keep_awake: ['cloude_billing-api', 'cloude_docs-site', 'cloude_billing-webhooks'],
      keep_awake_session_uuids: ['c30d7962-00bb-4e04-85fe-fe778155ef92', '804dd8df-1a26-4136-8df8-fd4dce5a91b3', '983a4348-f3e6-49a6-8eda-b37bf4570e3d'],
      mac_awake: true,
    },
    'GET /sessions/list': sessionList(),
    'GET /projects': projectList(),
  },
  empty: {
    'GET /auto-sleep': { ...SETTINGS, keep_awake: [], keep_awake_session_uuids: [], mac_awake: false },
    'GET /sessions/list': sessionList(),
    'GET /projects': projectList(),
  },
};
