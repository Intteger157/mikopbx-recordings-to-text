import axios from "axios";

const api = axios.create({
  baseURL: "/api",
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default api;

export type UserRole = "SUPERADMIN" | "MANAGER" | "USER";

export interface User {
  id: number;
  username: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  allowed_extensions: string[];
}

export interface CallRecord {
  id: number;
  uniqueid: string;
  linkedid: string | null;
  call_date: string;
  src_num: string | null;
  dst_num: string | null;
  duration: number;
  billsec: number;
  audio_url: string | null;
  miko_user_name: string | null;
  disposition: string | null;
  has_audio: boolean;
  transcription_status: TranscriptionStatus | null;
}

export type TranscriptionStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export interface TranscriptionSegment {
  start: number;
  end: number;
  text: string;
}

export interface Transcription {
  id: number;
  call_record_id: number;
  status: TranscriptionStatus;
  language: string | null;
  text: string | null;
  segments_json: TranscriptionSegment[] | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface CallRecordDetail extends CallRecord {
  transcription: Transcription | null;
}

export interface PaginatedCalls {
  items: CallRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface PBXConfig {
  api_url: string | null;
  has_api_key: boolean;
  is_connected: boolean;
  last_sync_at: string | null;
}

export interface Extension {
  id: number;
  extension: string;
  display_name: string | null;
  employee_id: string | null;
}
