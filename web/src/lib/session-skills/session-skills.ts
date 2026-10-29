import { stateToSend } from '../skills-page/skills-model';
import type { OverrideFile, SessionSkill } from '../skills-page/skills-types';

export interface SwitchTarget {
    readonly harness: 'claude' | 'codex';
    readonly file: OverrideFile;
    readonly projectPath: string | null;
}

export function switchTarget(skill: SessionSkill, family: string, workingDir: string | null): SwitchTarget | null {
    if (skill.scope === 'plugin' || skill.scope === 'system' || skill.shadowed_by !== null) return null;
    if (family === 'claude') {
        return workingDir ? { harness: 'claude', file: 'local', projectPath: workingDir } : null;
    }
    if (family === 'codex') {
        if (skill.scope === 'project') {
            return workingDir ? { harness: 'codex', file: 'project', projectPath: workingDir } : null;
        }
        return { harness: 'codex', file: 'user', projectPath: null };
    }
    return null;
}

export function isOn(skill: SessionSkill): boolean {
    return skill.state !== 'off';
}

export function stateFor(skill: SessionSkill, target: SwitchTarget, on: boolean): string | null | undefined {
    return stateToSend(on ? 'on' : 'off', skill.state_source, target.file, target.harness);
}
