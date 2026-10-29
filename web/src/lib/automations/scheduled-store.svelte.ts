import { resourcePush } from '../resource-push/boot';
import { taskManagerAddonOn } from '../task-manager-schedules/task-manager-addon.svelte';
import { readTaskManagerSchedules, TASK_MANAGER_TOPICS, type TaskManagerSchedule } from '../task-manager-schedules/task-manager-scheduled';

const POLL_MS = 30000;

export const scheduled = $state({ rows: [] as TaskManagerSchedule[], answered: false });

export async function loadScheduled(): Promise<void> {
  if (!taskManagerAddonOn()) {
    scheduled.rows = [];
    scheduled.answered = true;
    return;
  }
  try {
    scheduled.rows = await readTaskManagerSchedules();
  } catch {
  } finally {
    scheduled.answered = true;
  }
}

export function followScheduled(): () => void {
  void loadScheduled();
  return resourcePush().pushOrPoll(() => void loadScheduled(), POLL_MS, TASK_MANAGER_TOPICS);
}
