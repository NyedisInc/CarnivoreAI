import { mountPanel, unmountPanel } from '../mount';
import SoloPanel from './SoloPanel.svelte';

const PANEL_ID = 'solo-panel';

export interface SoloPanelProps extends Record<string, unknown> {
  kind: 'looking' | 'asleep' | 'gone' | 'ended';
  name?: string;
  sessionUuid?: string;
  agentType?: string;
}

export function showSoloPanel(props: SoloPanelProps): boolean {
  return mountPanel(PANEL_ID, SoloPanel, props) !== null;
}

export function hideSoloPanel(): boolean {
  return unmountPanel(PANEL_ID);
}
