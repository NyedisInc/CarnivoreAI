import manifest from '../../../../src/plugins/huddle/cplug.json';
import { cplugEnabled } from '../../plugins/host/enablement.svelte';
import { projectHasAgent } from '../../plugins/huddle/agents/agent-roster.svelte';
import type { CplugManifest } from '../../plugins/sdk';

export function agentOffered(project: { readonly id?: number | null }): boolean {
    const id = project.id ?? null;
    return id !== null && cplugEnabled(manifest as CplugManifest) && !projectHasAgent(id);
}
