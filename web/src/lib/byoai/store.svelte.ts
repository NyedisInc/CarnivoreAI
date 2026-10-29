import { startEvents, subscribe } from '../../opscenter/api/events.svelte';
import { errorText } from '../settings-page/panel-kit/error-text';
import {
    fetchConfig, fetchFeatures, fetchLedgerAccounts, fetchModels, fetchPresets,
    type AiConfig, type Feature, type Fetcher, type LedgerAccount, type ModelInfo, type Preset, type RecentModel,
} from './api';

export const ai = $state<{
    presets: Preset[];
    config: AiConfig | null;
    features: Feature[];
    accounts: LedgerAccount[];
    models: Record<string, readonly ModelInfo[] | 'error'>;
    recent: Record<string, readonly RecentModel[]>;
    problem: string;
}>({ presets: [], config: null, features: [], accounts: [], models: {}, recent: {}, problem: '' });

let fetcherInUse: Fetcher | undefined;
let inflight: Promise<void> | null = null;
let rereadAfter = false;
let attached = 0;
let detach: Array<() => void> = [];

export const presetOf = (id: string): Preset | undefined => ai.presets.find((p) => p.id === id);

export function refresh(): Promise<void> {
    if (inflight) {
        rereadAfter = true;
        return inflight;
    }
    inflight = readThenCatchUp().finally(() => { inflight = null; });
    return inflight;
}

async function readThenCatchUp(): Promise<void> {
    do {
        rereadAfter = false;
        await read();
    } while (rereadAfter);
}

async function read(): Promise<void> {
    try {
        const [presets, config, features] = await Promise.all([fetchPresets(fetcherInUse), fetchConfig(fetcherInUse), fetchFeatures(fetcherInUse)]);
        ai.presets = presets;
        ai.config = config;
        ai.features = features;
        ai.models = {};
        ai.recent = {};
        ai.problem = '';
    } catch (error) {
        ai.problem = errorText(error);
        return;
    }
    try {
        ai.accounts = await fetchLedgerAccounts(fetcherInUse);
    } catch {
        ai.accounts = [];
    }
}

export async function loadModels(connection: string, force = false): Promise<readonly ModelInfo[] | 'error'> {
    if (!force && ai.models[connection]) return ai.models[connection]!;
    try {
        const found = await fetchModels(connection, force, fetcherInUse);
        ai.recent[connection] = found.recent;
        ai.models[connection] = found.models;
    } catch {
        ai.models[connection] = 'error';
    }
    return ai.models[connection]!;
}

export function attach(fetcher?: Fetcher): () => void {
    if (fetcher) fetcherInUse = fetcher;
    attached += 1;
    if (attached === 1) {
        startEvents();
        detach = [subscribe('ai.config.changed', () => void refresh()), subscribe('events.hello', () => void refresh())];
    }
    void refresh();
    return () => {
        attached -= 1;
        if (attached === 0) {
            for (const stop of detach) stop();
            detach = [];
            fetcherInUse = undefined;
        }
    };
}
