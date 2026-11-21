import { t } from '../i18n/index.svelte';
import { ageWords } from '../computers/computers-format';
import type { SshState, SshTarget } from './ssh-targets-api';

export function shownState(target: SshTarget, changed: boolean): SshState {
  return changed && target.state !== 'taking_work' ? 'host_key_changed' : target.state;
}

export function stateWords(target: SshTarget, changed: boolean): string {
  const state = shownState(target, changed);
  switch (state) {
    case 'taking_work':
      return target.pressure?.pegged === true && target.pressure.why ? t('pack.ssh.state.taking_work_pegged', { why: target.pressure.why }) : t('pack.ssh.state.taking_work');
    case 'not_set_up':
    case 'off':
      return t('pack.ssh.state.off');
    case 'host_key_not_confirmed':
      return t('pack.ssh.state.host_key_not_confirmed');
    case 'host_key_changed':
      return t('pack.ssh.state.host_key_changed');
    case 'did_not_answer': {
      const age = target.last_ok_age_s;
      const line = t('pack.ssh.state.did_not_answer');
      return age === null || age === undefined ? line : `${line}, ${t('pack.ssh.state.last_figures', { age: ageWords(new Date(Date.now() - age * 1000).toISOString(), Date.now()) })}`;
    }
    case 'not_a_job_target':
      return t('pack.ssh.state.not_a_job_target');
    case 'host_disabled':
      return t('pack.ssh.state.host_disabled');
    default:
      return t('pack.ssh.state.unknown');
  }
}
