/* the Task Manager */
import manifest from '../../../../src/plugins/taskmanager/carnivore.toml';
import { cplugEnabled } from '../../plugins/host/enablement.svelte';
import { projectHasAgent } from '../../plugins/taskmanager/agents/agent-roster.svelte';
import type { CplugManifest } from '../../plugins/sdk';

export function agentOffered(project: { readonly id?: number | null }): boolean {
    const id = project.id ?? null;
    return id !== null && cplugEnabled(manifest as CplugManifest) && !projectHasAgent(id);
}
