import { registerBoardHeaderKey } from '../board-header-keys';
import { publicLinksOn } from './public-links-on';
import ShareLinkKey from './ShareLinkKey.svelte';
import VisitorsKey from './VisitorsKey.svelte';
import { registerVisitorSource } from './visitor-source';

export function registerBoardKeys(): void {
  registerBoardHeaderKey({ id: 'reviewboard.share', component: ShareLinkKey, enabled: publicLinksOn });
  registerBoardHeaderKey({ id: 'reviewboard.visitors', component: VisitorsKey, enabled: publicLinksOn });
  registerVisitorSource(); // the history bar
}
