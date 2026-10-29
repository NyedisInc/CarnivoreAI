
export interface ContentsItem {
  name: string;
  scope: string;
  path: string | null;
  description: string;
  detail: string;
  lines: number | null;
  open_root: string | null;
  open_path: string | null;
  status: string;
}

export interface ContentsSection {
  kind: string;
  items: ContentsItem[];
  truncated: boolean;
}

export interface SessionContents {
  session_uuid: string;
  row_id: number;
  family: string;
  config_dir: string;
  working_dir: string | null;
  sections: ContentsSection[];
}
