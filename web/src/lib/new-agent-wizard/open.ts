import { openModal } from '../modal';
import { beginNav } from '../launchpad/nav-generation';
import type { CreateHost, CreatedSession } from '../launchpad/create-host';
import { t as appT } from '../i18n/index.svelte';
import type { Translate } from '../sessions/types';
import NewAgentWizardModal from './NewAgentWizardModal.svelte';
import type { WizardApi } from './api';
import type { WizardAdjacentContext, WizardEntryContext, WizardProject } from './model';

export interface OpenNewAgentWizardOptions {
    entryContext?: WizardEntryContext;
    adjacent?: WizardAdjacentContext | null;
    initialProject?: WizardProject | null;
    initialAgentName?: string;
    api?: WizardApi;
}

export interface WizardOutcome {
    session: CreatedSession;
}

export async function openNewAgentWizard(
    host: CreateHost,
    options: OpenNewAgentWizardOptions = {},
    t: Translate = appT,
): Promise<CreatedSession | null> {
    const nav = beginNav('create');
    const result = await openModal<WizardOutcome, Record<string, unknown>>(
        NewAgentWizardModal as never,
        {
            entryContext: options.entryContext ?? 'top_plus',
            adjacent: options.adjacent ?? null,
            initialProject: options.initialProject ?? null,
            initialAgentName: options.initialAgentName ?? '',
            terminalDims: () => host.terminalDims(),
            onProjectSaved: () => {
                void host.reloadProjects().catch((err) => {
                    console.error('CloudeWeb: failed to refresh projects after project creation:', err);
                });
            },
            ...(options.api ? { api: options.api } : {}),
            t,
        },
    );
    if (!result?.session) return null;
    host.announceSessionCreated(result.session, nav);
    try {
        await host.reloadProjects();
    } catch (err) {
        console.error('CloudeWeb: failed to refresh projects after wizard launch:', err);
    }
    return result.session;
}
