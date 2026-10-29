
export interface TrailMessage {
  id: string;
  thread: string;
  sender_name: string;
  receiver_name: string | null;
  created_at: number;
  status: string;
  preview: string;
}

export function trailPath(itemId: number): string {
  return `/crosstalk/task-items/${itemId}/messages?limit=50`;
}

export function trailWho(message: TrailMessage, unknown: string): string {
  return `${message.sender_name || unknown} > ${message.receiver_name || unknown}`;
}
