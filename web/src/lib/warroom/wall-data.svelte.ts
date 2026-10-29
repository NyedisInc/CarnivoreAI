import { sessions, asleep, projects } from '../../opscenter/api';
import { browsers } from '../browser/api.svelte';
import { projectColorOf } from '../project-colors/store.svelte';
import { t } from '../i18n/index.svelte';
import { buildWall, type TileGroup, type WarroomToggles } from './warroom-model';

export function wallGroups(toggles: WarroomToggles): TileGroup[] {
  return buildWall({
    sessions: sessions.data ?? [],
    asleep: toggles.asleep ? (asleep.data ?? []) : [],
    browsers: toggles.browsers ? (browsers.data ?? []) : [],
    projects: projects.data ?? [],
    toggles,
    colorOf: projectColorOf,
    unfiledLabel: t('warroom.group.unfiled'),
    browsersLabel: t('warroom.group.browsers'),
  });
}

export function wallLoaded(): boolean {
  return sessions.data !== null;
}
