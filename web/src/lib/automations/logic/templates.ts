export interface Template {
  id: 'morning_digest' | 'nightly_command' | 'weekly_card' | 'health_ping';
  kind: 'agent' | 'command' | 'swarm_card' | 'recipe';
  cron: string;
}

export const TEMPLATES: readonly Template[] = [
  { id: 'morning_digest', kind: 'agent', cron: '30 7 * * 1-5' },
  { id: 'nightly_command', kind: 'command', cron: '0 2 * * *' },
  { id: 'weekly_card', kind: 'swarm_card', cron: '0 9 * * 1' },
  { id: 'health_ping', kind: 'recipe', cron: '*/30 * * * *' },
];

export function templateNameKey(t: Template): string {
  return `automations.page.template.${t.id}.name`;
}

export function templateTextKey(t: Template): string {
  return `automations.page.template.${t.id}.text`;
}
