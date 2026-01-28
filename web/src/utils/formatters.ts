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
    // 如果时间字符串没有时区信息，假设它是UTC时间并添加'Z'后缀
    let dateStr = dateString.trim()
    
    // 检查是否已经有时区信息
    // 1. 以'Z'结尾表示UTC
    // 2. 以'+'或'-'开头后跟时区偏移（如+08:00, -05:00, +0800等）
    const hasTimezone = /Z$/.test(dateStr) || 
                       /[+-]\d{2}:?\d{2}$/.test(dateStr) ||
                       /[+-]\d{4}$/.test(dateStr)
    
    if (!hasTimezone) {
      // 格式类似 "2024-01-26T10:30:00" 或 "2024-01-26T10:30:00.123" 没有时区信息
      // 移除可能的微秒部分，然后添加'Z'表示UTC
      if (dateStr.includes('.')) {
        // 有微秒，保留到秒
        dateStr = dateStr.split('.')[0] + 'Z'
      } else {
        // 没有微秒，直接添加'Z'
        dateStr = dateStr + 'Z'
      }
    }
    
    const date = new Date(dateStr)
    
    // 检查日期是否有效
    if (isNaN(date.getTime())) {
      console.warn('Invalid date string:', dateString)
      return dateString
    }
    
    // 转换为中国时区显示（UTC+8）
    return date.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    })
  } catch (error) {
    console.error('Error formatting date:', dateString, error)
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
