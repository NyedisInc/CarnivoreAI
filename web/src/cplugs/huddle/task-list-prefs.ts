import { authFetch } from '../sdk';

interface ListPrefs {
  list: string;
  nudge: boolean;
}

interface InboxPrefs {
  list: string;
  file_through_session: boolean;
}

function prefsPath(projectId: number): string {
  return `/cplugs/huddle/lists/${projectId}/prefs`;
}

export async function getListNudge(projectId: number): Promise<boolean> {
  return (await authFetch<ListPrefs>(prefsPath(projectId))).nudge === true;
}

export async function setListNudge(projectId: number, on: boolean): Promise<boolean> {
  const stored = await authFetch<ListPrefs>(prefsPath(projectId), { method: 'PUT', body: JSON.stringify({ nudge: on }) });
  return stored.nudge === true;
}

export async function getListInbox(projectId: number): Promise<boolean> {
  return (await authFetch<InboxPrefs>(`/cplugs/huddle/lists/${projectId}/inbox-prefs`)).file_through_session === true;
}

export async function setListInbox(projectId: number, on: boolean): Promise<boolean> {
  const stored = await authFetch<InboxPrefs>(`/cplugs/huddle/lists/${projectId}/inbox-prefs`, {
    method: 'PUT', body: JSON.stringify({ file_through_session: on }),
  });
  return stored.file_through_session === true;
}
