
export type TaskManagerReadLane = 'lists' | 'aggregate' | 'body' | 'thread';

export interface TaskManagerReadOrder {
  begin(): number;
  accepts(ticket: number, lane: TaskManagerReadLane): boolean;
  writeStarted(): void;
  writeSettled(): void;
  needsReread(): boolean;
}

export function createReadOrder(): TaskManagerReadOrder {
  let issued = 0;
  let floor = 0;
  let writing = 0;
  let owed = false;
  const painted: Record<TaskManagerReadLane, number> = { lists: 0, aggregate: 0, body: 0, thread: 0 };
  return {
    begin() {
      issued += 1;
      return issued;
    },
    accepts(ticket, lane) {
      if (writing > 0 || ticket <= floor) {
        owed = true;
        return false;
      }
      if (ticket < painted[lane]) return false;
      painted[lane] = ticket;
      return true;
    },
    writeStarted() {
      writing += 1;
      floor = issued;
    },
    writeSettled() {
      writing = Math.max(0, writing - 1);
      floor = issued;
    },
    needsReread() {
      if (!owed || writing > 0) return false;
      owed = false;
      return issued <= floor;
    },
  };
}
