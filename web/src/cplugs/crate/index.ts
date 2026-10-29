import manifest from '../../../../src/cplugs/crate/cplug.json';
import type { Component } from 'svelte';
import type { CplugManifest, CplugWeb, Contribution } from '../sdk';
import { cplugEnabled, registerProjectPanel } from '../sdk';
import CratePanel from './CratePanel.svelte';
import ProjectCrates from './ProjectCrates.svelte';

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
