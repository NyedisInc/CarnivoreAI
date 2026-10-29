import manifest from '../../../../src/cplugs/huddle/cplug.json';
import { cplugEnabled } from '../../cplugs/host/enablement.svelte';
import { projectHasAgent } from '../../cplugs/huddle/agents/agent-roster.svelte';
import type { CplugManifest } from '../../cplugs/sdk';

export function agentOffered(project: { readonly id?: number | null }): boolean {
    const id = project.id ?? null;
    return id !== null && cplugEnabled(manifest as CplugManifest) && !projectHasAgent(id);
}
