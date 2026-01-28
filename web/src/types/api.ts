export interface ServerStatus {
  server_status: string
  uptime: string
  telegram_bot: string
  connected_bots: number
  loads: Record<string, number>
  version: string
}

export interface UploadRecord {
  id: number
  upload_target: string
  status: 'pending' | 'waiting_download' | 'uploading' | 'completed' | 'failed' | 'cancelled' | 'paused'
  total_size?: number
  uploaded_size?: number
  upload_speed?: number
  failure_reason?: string
  error_message?: string
  created_at?: string
  started_at?: string
  completed_at?: string
  cleaned_at?: string
  updated_at?: string
  file_name?: string
  remote_path?: string
  download_id?: number
}

export interface DownloadRecord {
  id: number
  gid?: string
  source_url?: string
  status: 'pending' | 'downloading' | 'completed' | 'failed' | 'skipped'
  total_length?: number
  completed_length?: number
  download_speed?: number
  error_message?: string
  local_path?: string
  remote_path?: string
  upload_status?: string
  updated_at?: string
  created_at: string
  started_at?: string
  completed_at?: string
  file_name?: string
  mime_type?: string
  file_size?: number
  chat_id?: number
  message_id?: number
  media_group_id?: string
  caption?: string
  message_date?: string
  uploads?: UploadRecord[]
}

export interface DownloadGroup {
  group_key: string
  group_type: 'media_group' | 'message' | 'single'
  chat_id?: number
  message_id?: number
  media_group_id?: string
  caption?: string
  message_date?: string
  created_at: string
  stats: {
    total_files: number
    completed: number
    downloading: number
    failed: number
    pending: number
    skipped?: number
    total_size: number
    completed_size: number
  }
  downloads: DownloadRecord[]
}

export interface DownloadsResponse {
  success: boolean
  limit: number
  count: number
  group_count?: number
  grouped?: boolean
  data: DownloadRecord[] | DownloadGroup[]
}

export interface DockerStatus {
  success: boolean
  in_docker?: boolean
  container_name?: string
  status?: string
  image?: string
  created?: string
  error?: string
}

export interface DockerRestartResponse {
  success: boolean
  message?: string
  container_name?: string
  error?: string
}

export interface DockerLogsResponse {
  success: boolean
  logs?: string
  lines?: number
  error?: string
}

export interface ConfigResponse {
  success: boolean
  data?: Record<string, any>
  error?: string
}

export interface ConfigUpdateResponse {
  success: boolean
  message?: string
  updated_count?: number
  needs_restart?: boolean
  error?: string
}
