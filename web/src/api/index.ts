import axios from 'axios'
import type {
  ServerStatus,
  DownloadsResponse,
  DockerStatus,
  DockerRestartResponse,
  DockerLogsResponse,
  ConfigResponse,
  ConfigUpdateResponse,
  SystemResourcesResponse
} from '@/types/api'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
})

export function getStatus(): Promise<ServerStatus> {
  return api.get<ServerStatus>('/status').then(response => response.data)
}

export function getDownloads(limit = 100, grouped = true): Promise<DownloadsResponse> {
  return api.get<DownloadsResponse>('/downloads', {
    params: { limit, grouped }
  }).then(response => response.data)
}

export function getDockerStatus(): Promise<DockerStatus> {
  return api.get<DockerStatus>('/system/docker/status').then(response => response.data)
}

export function restartDocker(): Promise<DockerRestartResponse> {
  return api.post<DockerRestartResponse>('/system/docker/restart').then(response => response.data)
}

export function getDockerLogs(lines = 100): Promise<DockerLogsResponse> {
  return api.get<DockerLogsResponse>('/system/docker/logs', {
    params: { lines }
  }).then(response => response.data)
}

export function getSystemResources(): Promise<SystemResourcesResponse> {
  return api.get<SystemResourcesResponse>('/system/resources').then(response => response.data)
}

export function getConfig(category?: string): Promise<ConfigResponse> {
  return api.get<ConfigResponse>('/config', {
    params: category ? { category } : {}
  }).then(response => response.data)
}

export function updateConfig(config: Record<string, any>): Promise<ConfigUpdateResponse> {
  return api.post<ConfigUpdateResponse>('/config', config).then(response => response.data)
}

export function reloadConfig(): Promise<ConfigUpdateResponse> {
  return api.post<ConfigUpdateResponse>('/config/reload').then(response => response.data)
}

export interface QueueStatus {
  success: boolean
  current_processing: any | null
  waiting_count: number
  waiting_items: any[]
  queue_size: number
  error?: string
}

export function getQueue(): Promise<QueueStatus> {
  return api.get<QueueStatus>('/queue').then(response => response.data)
}

export interface TrendPoint {
  timestamp: number
  upload: number
  download: number
  io: number
}

export interface TrendResponse {
  success: boolean
  data: TrendPoint[]
  error?: string
}

export function getSystemTrend(): Promise<TrendResponse> {
  return api.get<TrendResponse>('/monitor/trend').then(response => response.data)
}

export interface DownloadStatistics {
  total: number
  completed: number
  downloading: number
  failed: number
  pending: number
  waiting: number
  total_size: number
  completed_size: number
}

export interface DownloadStatisticsResponse {
  success: boolean
  data: DownloadStatistics
  error?: string
}

export function getDownloadStatistics(): Promise<DownloadStatisticsResponse> {
  return api.get<DownloadStatisticsResponse>('/downloads/statistics').then(response => response.data)
}

export interface DeleteAllDownloadsResponse {
  success: boolean
  message?: string
  data?: {
    deleted_downloads: number
    deleted_media: number
  }
  error?: string
}

export function deleteAllDownloads(): Promise<DeleteAllDownloadsResponse> {
  return api.delete<DeleteAllDownloadsResponse>('/downloads/all').then(response => response.data)
}

export interface UploadStatistics {
  total: number
  uploading: number
  completed: number
  failed: number
  pending: number
  cleaned: number
}

export interface UploadStatisticsResponse {
  success: boolean
  data: UploadStatistics
  error?: string
}

export function getUploadStatistics(): Promise<UploadStatisticsResponse> {
  return api.get<UploadStatisticsResponse>('/uploads/statistics').then(response => response.data)
}

export interface UploadsResponse {
  success: boolean
  limit: number
  count: number
  data: UploadRecord[]
  error?: string
}

export function getUploads(limit = 100, status?: string, uploadTarget?: string): Promise<UploadsResponse> {
  return api.get<UploadsResponse>('/uploads', {
    params: { limit, status, upload_target: uploadTarget }
  }).then(response => response.data)
}

// ==================== 下载任务控制 API ====================

export interface TaskControlResponse {
  success: boolean
  message?: string
  new_gid?: string
  error?: string
}

export function retryDownload(gid: string): Promise<TaskControlResponse> {
  return api.post<TaskControlResponse>(`/downloads/${gid}/retry`).then(response => response.data)
}

export function deleteDownload(gid: string): Promise<TaskControlResponse> {
  return api.delete<TaskControlResponse>(`/downloads/${gid}`).then(response => response.data)
}

export interface DeleteRecordResponse {
  success: boolean
  message?: string
  data?: {
    download_deleted: boolean
    upload_count: number
    media_deleted: boolean
    file_deleted: boolean
    local_path?: string
  }
  error?: string
}

export function deleteDownloadRecord(downloadId: number, deleteFile: boolean = true): Promise<DeleteRecordResponse> {
  return api.delete<DeleteRecordResponse>(`/downloads/record/${downloadId}`, {
    params: { delete_file: deleteFile }
  }).then(response => response.data)
}

// ==================== 上传任务控制 API ====================

export function retryUpload(uploadId: number): Promise<TaskControlResponse> {
  return api.post<TaskControlResponse>(`/uploads/${uploadId}/retry`).then(response => response.data)
}

export function deleteUpload(uploadId: number): Promise<TaskControlResponse> {
  return api.delete<TaskControlResponse>(`/uploads/${uploadId}`).then(response => response.data)
}
