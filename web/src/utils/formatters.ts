export function formatSize(bytes?: number): string {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(2)} ${units[unitIndex]}`
}

export function formatDate(dateString?: string): string {
  if (!dateString) return '-'
  try {
    const date = new Date(dateString)
    return date.toLocaleString('zh-CN')
  } catch {
    return dateString
  }
}

export function truncatePath(path?: string, maxLength = 50): string {
  if (!path) return '-'
  if (path.length > maxLength) {
    return '...' + path.substring(path.length - (maxLength - 3))
  }
  return path
}

export function getProgress(
  totalLength?: number,
  completedLength?: number,
  status?: string
): number {
  if (status === 'completed') return 100
  if (status === 'pending') return 0
  if (totalLength && completedLength) {
    return Math.round((completedLength / totalLength) * 100)
  }
  return 0
}

export function getStatusText(status?: string): string {
  const statusMap: Record<string, string> = {
    completed: '已完成',
    downloading: '下载中',
    failed: '失败',
    pending: '等待中',
    skipped: '已跳过'
  }
  return statusMap[status || ''] || status || '未知'
}

export function getStatusTagType(status?: string): 'success' | 'warning' | 'danger' | 'info' {
  const typeMap: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
    completed: 'success',
    downloading: 'warning',
    failed: 'danger',
    pending: 'info',
    skipped: 'info'
  }
  return typeMap[status || ''] || 'info'
}
