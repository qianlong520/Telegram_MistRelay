import axios from 'axios'
import type {
  ServerStatus,
  DownloadsResponse,
  DockerStatus,
  DockerRestartResponse,
  DockerLogsResponse,
  ConfigResponse,
  ConfigUpdateResponse
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
