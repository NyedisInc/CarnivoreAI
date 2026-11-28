import manifest from '../../../../src/plugins/crate/carnivore.toml';
import type { Component } from 'svelte';
import type { CplugManifest, CplugWeb, Contribution } from '../sdk';
import { cplugEnabled, lazyComponent, registerProjectPanel } from '../sdk';

const CratePanel = lazyComponent(() => import('./CratePanel.svelte'));
const ProjectCrates = lazyComponent(() => import('./ProjectCrates.svelte'));

export const SETTINGS_PANEL_ID = 'crate';
export const PROJECT_PANEL_ID = 'crate.crates';

const settingsPanel: Contribution<'settings-panel'> = {
    id: SETTINGS_PANEL_ID,
    surface: 'settings-panel',
    enabled: () => true,
    payload: { Panel: CratePanel as unknown as Component<Record<string, never>> },
};

export const crateCplug: CplugWeb = {
    id: 'crate',
    manifest: manifest as CplugManifest,
    plugins: [settingsPanel as unknown as Contribution],
    start: () => {
        registerProjectPanel({
            id: PROJECT_PANEL_ID, labelKey: 'cplug.crate.project.group', hintKey: 'cplug.crate.project.hint', component: ProjectCrates,
            enabled: () => cplugEnabled(crateCplug.manifest),
        });
    },
};
