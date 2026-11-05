import { FIXTURE_PLUGIN_ID, FIXTURE_VIEW, FIXTURE_VIEW_PATH } from '../../../widget-harness/plugin-view-fixture';
import type { RouteTable, WidgetFixtures } from './types';

const TICKET: RouteTable = {
  [`POST /cplugs/${FIXTURE_PLUGIN_ID}/view/${FIXTURE_VIEW}/ticket`]: { path: FIXTURE_VIEW_PATH, expires_in: 60 },
};

export const pluginViewFixtures: WidgetFixtures = { data: TICKET, empty: TICKET };
