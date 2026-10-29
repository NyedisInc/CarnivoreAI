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
      keep_awake_session_uuids: ['6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d301', '6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d302', '6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d303'],
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
