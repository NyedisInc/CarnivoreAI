import { inNativeShell } from '../native-shell/shell';
import { nodeHash, type PublishTab } from './menu/route';

export function openPublishPage(tab: PublishTab = 'submissions'): void {
    if (inNativeShell()) return;
    try {
        const hash = nodeHash({ scope: 'publish', page: 'tab', tab });
        if (globalThis.location) globalThis.location.hash = hash;
    } catch {
    }
}
