export interface CrosstalkMessage {
  id: string; source: string; thread: string;
  sender_id: string; sender_uuid: string | null; sender_name: string;
  sender_provider: string; sender_model: string;
  receiver_id: string; receiver_uuid: string | null;
  receiver_name?: string | null; receiver_provider?: string | null; receiver_model?: string | null;
  text: string; status: string; created_at: number;
}
