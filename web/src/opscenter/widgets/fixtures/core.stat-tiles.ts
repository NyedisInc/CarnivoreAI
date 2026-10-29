import { closedSessionsFixtures } from './core.closed-sessions';
import { ledgerFixtures } from './core.ledger';
import { runningSessionsFixtures } from './core.running-sessions';
import type { WidgetFixtures } from './types';

const SOURCES: readonly WidgetFixtures[] = [runningSessionsFixtures, closedSessionsFixtures, ledgerFixtures];

export const statTileFixtures: WidgetFixtures = {
  data: Object.assign({}, ...SOURCES.map((pair) => pair.data)),
  empty: Object.assign({}, ...SOURCES.map((pair) => pair.empty)),
};
