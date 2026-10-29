import { authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export type CliState = 'installed' | 'missing' | 'stale' | 'foreign';

export type CliOutcome = 'installed' | 'already_installed' | 'cancelled' | 'timed_out' | 'foreign' | 'failed';

export interface CliCommand {
    readonly state: CliState;
    readonly command: string;
    readonly link_path: string;
    readonly shim_path: string;
    readonly manual_command: string;
    readonly run_from_checkout: string;
}

export interface CliInstall {
    readonly outcome: CliOutcome;
    readonly state: CliState;
    readonly detail: string;
}

const ROUTE = '/cli-command';

export const getCliCommand = (fetcher: Fetcher = authFetch) => fetcher<CliCommand>(ROUTE);

export const installCliCommand = (fetcher: Fetcher = authFetch) => fetcher<CliInstall>(`${ROUTE}/install`, { method: 'POST' });
