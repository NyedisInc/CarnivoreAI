import { unread as byMessages, type Task } from './model';

export const unread = (task: Pick<Task, 'unread' | 'messages'>): boolean => task.unread ?? byMessages(task as Task);
