// Типы данных клиента. Портированы из desktop/src/types.ts без изменений —
// формат API общий для десктопа и веба.

export interface User {
  id: number;
  username: string;
  display_name?: string | null;
  avatar?: string | null;
  profile_color?: string | null;
  bio?: string | null;
  status?: string | null;
  is_online?: boolean;
}

export interface Room {
  id: number;
  name: string;
  member_count?: number;
  members?: User[];
}

export interface Conversation {
  id?: number;
  user?: User;
}

export interface Msg {
  id?: number | string;
  content?: string;
  created_at?: string;
  // комнатные сообщения
  user_id?: number;
  user?: User;
  // личные
  sender_id?: number;
  sender?: User;
}

export type Current =
  | { kind: "room"; id: string; key: string; label: string }
  | { kind: "dm"; id: string; key: string; label: string };

export interface WsEvent {
  type: string;
  user_id?: number;
  online?: boolean;
  room_id?: number | string;
  conversation_id?: number;
  from_id?: number;
  message?: Msg;
  // сигналинг звонков (сервер — реле; аудио идёт Opus по бинарному сокету)
  to_id?: number | string;
  call_id?: string | null;
  sdp?: { type?: string; sdp: string };
  candidate?: RTCIceCandidateInit;
  reason?: string;
  audio?: string;
  seq?: number;
  // демонстрация экрана (видео по бинарному сокету)
  codec?: string;
  width?: number;
  height?: number;
  key?: boolean;
  data?: string;
}

export interface AuthResult {
  access_token: string;
  user: User;
}
