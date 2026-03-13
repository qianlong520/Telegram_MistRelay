<template>
  <div class="drive-page" v-loading="previewLoading">
    <el-card shadow="hover">
      <template #header>
        <div class="drive-header">
          <div>
            <h2>我的网盘</h2>
            <p class="drive-header-subtitle">浏览远程存储、查看容量并管理文件</p>
          </div>

          <div v-if="availableRemotes.length > 0" class="drive-header-tools">
            <el-select
              v-model="currentRemote"
              @change="handleRemoteChange"
              placeholder="选择云存储"
              class="header-remote-select"
              popper-class="drive-remote-popper"
              fit-input-width
            >
              <el-option
                v-for="remote in availableRemotes"
                :key="remote.name"
                :label="remote.name"
                :value="remote.name"
              >
                <div class="remote-option">
                  <div class="remote-option-head">
                    <span class="remote-option-name">{{ remote.name }}</span>
                    <el-tag size="small" effect="plain" round>{{ remote.type }}</el-tag>
                  </div>
                  <div class="remote-option-meta">
                    <span>{{ getRemoteUsageSummary(remote.name) }}</span>
                    <span v-if="getRemoteUsagePercent(remote.name) !== null" class="remote-option-percent">
                      {{ getRemoteUsagePercent(remote.name)!.toFixed(0) }}%
                    </span>
                  </div>
                </div>
              </el-option>
            </el-select>

            <div v-if="currentRemote" class="header-usage">
              <template v-if="loadingDriveUsage">
                <span class="header-usage-text">容量读取中...</span>
              </template>
              <template v-else-if="driveUsage?.supported && driveUsage.data">
                <span class="header-usage-name">{{ currentRemote }}</span>
                <span class="header-usage-text">{{ formatBytes(driveUsage.data.used) }} / {{ formatBytes(driveUsage.data.total) }}</span>
                <el-tag size="small" round :type="usagePercent >= 90 ? 'danger' : usagePercent >= 75 ? 'warning' : 'success'">
                  {{ usagePercent.toFixed(1) }}%
                </el-tag>
              </template>
              <template v-else>
                <span class="header-usage-name">{{ currentRemote }}</span>
                <span class="header-usage-text">{{ driveUsage?.error || '暂不支持容量统计' }}</span>
              </template>

              <el-button :icon="RefreshRight" circle size="small" @click="loadDriveUsage(true, true)" :loading="loadingDriveUsage" />
            </div>
          </div>
        </div>
      </template>

      <div class="drive-topbar">
        <div class="drive-controls">
          <el-button
            class="drive-nav-button"
            :icon="ArrowLeft"
            :disabled="!canNavigateUp"
            @click="navigateUp"
          >
            返回上级
          </el-button>

          <div class="drive-breadcrumb-card">
            <el-breadcrumb separator="/">
              <el-breadcrumb-item @click="navigateToPath('/')">
                <el-icon><HomeFilled /></el-icon>
                根目录
              </el-breadcrumb-item>
              <el-breadcrumb-item
                v-for="(segment, index) in pathSegments"
                :key="index"
                @click="navigateToSegment(index)"
              >
                {{ segment }}
              </el-breadcrumb-item>
            </el-breadcrumb>
          </div>

          <div class="drive-actions">
            <el-button-group class="view-mode-toggle">
              <el-button :type="viewMode === 'list' ? 'primary' : ''" @click="viewMode = 'list'">
                <el-icon><List /></el-icon>
              </el-button>
              <el-button :type="viewMode === 'grid' ? 'primary' : ''" @click="viewMode = 'grid'">
                <el-icon><Grid /></el-icon>
              </el-button>
            </el-button-group>

            <el-select
              v-model="currentSort"
              placeholder="排序"
              class="sort-select"
            >
              <template #prefix>
                <el-icon><Sort /></el-icon>
              </template>
              <el-option
                v-for="item in sortOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>

            <el-input
              v-model="searchKeyword"
              placeholder="搜索文件名"
              clearable
              class="search-input"
              :prefix-icon="Search"
            />
          </div>
        </div>
      </div>

      <!-- 列表视图 -->
      <el-table
        v-if="viewMode === 'list'"
        :data="paginatedItems"
        v-loading="loading"
        style="width: 100%; margin-top: 20px"
        @row-click="handleRowClick"
        :row-style="{ cursor: 'pointer' }"
      >
        <el-table-column label="名称" min-width="200">
          <template #default="{ row }">
            <div class="file-name">
              <el-icon :size="18" style="margin-right: 8px">
                <Folder v-if="row.isDir" />
                <Picture v-else-if="isImage(row.name)" />
                <VideoPlay v-else-if="isVideo(row.name)" />
                <Document v-else />
              </el-icon>
              {{ row.name }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="size" label="大小" width="120">
          <template #default="{ row }">
            {{ row.isDir ? '-' : formatBytes(row.size) }}
          </template>
        </el-table-column>
        <el-table-column prop="modTime" label="修改时间" width="180">
          <template #default="{ row }">
            {{ formatDate(row.modTime) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="center">
          <template #default="{ row }">
            <el-button-group>
              <el-button
                v-if="!row.isDir" 
                type="primary" 
                link 
                :icon="Download"
                :loading="Boolean(downloadingPaths[row.path])"
                @click.stop="handleDownload(row)"
              />
              <el-button 
                type="danger" 
                link 
                :icon="Delete"
                @click.stop="handleDelete(row)"
              />
            </el-button-group>
          </template>
        </el-table-column>
      </el-table>

      <!-- 网格视图 -->
      <div v-else class="grid-view">
        <div
          v-for="item in paginatedItems"
          :key="item.path"
          class="grid-item"
          @click="handleRowClick(item)"
        >
          <div class="grid-item-preview">
            <el-icon v-if="item.isDir" :size="48" class="grid-icon">
              <Folder />
            </el-icon>
            <el-image
              v-else-if="isImage(item.name)"
              :src="getThumbnailUrl(item)"
              fit="cover"
              class="grid-thumbnail"
              lazy
            >
              <template #placeholder>
                <div class="image-placeholder">
                  <el-icon :size="48"><Picture /></el-icon>
                </div>
              </template>
              <template #error>
                <div class="image-placeholder">
                  <el-icon :size="48"><Picture /></el-icon>
                </div>
              </template>
            </el-image>
            <div v-else-if="isVideo(item.name)" class="grid-video">
              <el-image
                :src="getThumbnailUrl(item)"
                fit="cover"
                class="grid-thumbnail"
                lazy
              >
                <template #placeholder>
                  <div class="video-placeholder">
                    <el-icon :size="48"><VideoPlay /></el-icon>
                  </div>
                </template>
                <template #error>
                  <div class="video-placeholder">
                    <el-icon :size="48"><VideoPlay /></el-icon>
                  </div>
                </template>
              </el-image>
              <div class="video-badge">视频</div>
            </div>
            <el-icon v-else :size="48" class="grid-icon">
              <Document />
            </el-icon>
          </div>
          <div class="grid-item-name" :title="item.name">{{ item.name }}</div>
          <div class="grid-item-info">
             <div v-if="!item.isDir" class="grid-item-size">{{ formatBytes(item.size) }}</div>
             <div class="grid-item-actions">
               <el-button 
                 v-if="!item.isDir"
                 circle 
                 size="small" 
                 :icon="Download"
                 :loading="Boolean(downloadingPaths[item.path])"
                 @click.stop="handleDownload(item)"
               />
               <el-button 
                 circle 
                 size="small" 
                 type="danger" 
                 :icon="Delete"
                 @click.stop="handleDelete(item)"
               />
             </div>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div class="pagination-container">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="filteredItems.length"
          layout="total, sizes, prev, pager, next, jumper"
          background
        />
      </div>

      <!-- 空状态 -->
      <el-empty v-if="!loading && items.length === 0" description="此目录为空" />
    </el-card>

    <!-- 图片预览 -->
    <el-image-viewer
      v-if="showPreview && previewType === 'image'"
      :url-list="[previewUrl]"
      @close="closePreview"
      hide-on-click-modal
    />

    <!-- 视频播放 -->
    <el-dialog
      v-model="showPreview"
      v-if="previewType === 'video'"
      :title="previewItem?.name"
      width="80%"
      destroy-on-close
      @close="closePreview"
      center
      class="video-dialog"
    >
      <div class="video-container">
        <VideoPlayer 
          v-if="showPreview && previewType === 'video' && previewUrl"
          :src="previewUrl" 
          :type="getVideoType(previewItem?.name)"
          :remote="currentRemote"
          :path="previewItem?.path"
        />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { HomeFilled, Document, Folder, Search, List, Grid, Picture, VideoPlay, Sort, Download, Delete, RefreshRight, ArrowLeft } from '@element-plus/icons-vue'
import { getRcloneRemotes, browseDrive, getThumbnail, deleteFile, getDriveUsage, type RcloneRemote, type DriveItem, type DriveUsageResponse } from '@/api'
import VideoPlayer from '@/components/VideoPlayer.vue'
import { buildAuthorizedApiUrl } from '@/utils/runtime'

interface RemoteUsageState {
  response?: DriveUsageResponse
  loading: boolean
}

const availableRemotes = ref<RcloneRemote[]>([])
const currentRemote = ref('')
const currentPath = ref('/')
const items = ref<DriveItem[]>([])
const loading = ref(false)
const remoteUsageStates = ref<Record<string, RemoteUsageState>>({})

// 搜索和分页
const searchKeyword = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

// 视图模式
const viewMode = ref<'list' | 'grid'>('list')

// 排序状态
const sortBy = ref<'name' | 'time'>('time')
const sortDesc = ref(true) // 默认降序(最新的在前)

// 排序选项
const sortOptions = [
  { label: '时间 (新→旧)', value: 'time-desc' },
  { label: '时间 (旧→新)', value: 'time-asc' },
  { label: '名称 (A→Z)', value: 'name-asc' },
  { label: '名称 (Z→A)', value: 'name-desc' },
]

const currentSort = computed({
  get: () => `${sortBy.value}-${sortDesc.value ? 'desc' : 'asc'}`,
  set: (val) => {
    const [field, order] = val.split('-')
    sortBy.value = field as 'name' | 'time'
    sortDesc.value = order === 'desc'
  }
})

const currentRemoteInfo = computed(() => {
  return availableRemotes.value.find(remote => remote.name === currentRemote.value) || null
})

const currentRemoteState = computed(() => {
  if (!currentRemote.value) return null
  return remoteUsageStates.value[currentRemote.value] || null
})

const driveUsage = computed(() => currentRemoteState.value?.response || null)
const loadingDriveUsage = computed(() => currentRemoteState.value?.loading || false)

const usagePercent = computed(() => {
  const total = driveUsage.value?.data?.total
  const used = driveUsage.value?.data?.used
  if (!total || !used || total <= 0) return 0
  return Math.min(100, Number(((used / total) * 100).toFixed(1)))
})

const usageProgressColor = computed(() => {
  if (usagePercent.value >= 90) return '#ef4444'
  if (usagePercent.value >= 75) return '#f59e0b'
  return '#10b981'
})

// 计算属性
const pathSegments = computed(() => {
  const path = currentPath.value
  if (path === '/') return []
  return path.split('/').filter(Boolean)
})

const parentPath = computed(() => {
  const path = currentPath.value || '/'
  if (path === '/') return null

  const segments = path.split('/').filter(Boolean)
  if (segments.length <= 1) return '/'
  return `/${segments.slice(0, -1).join('/')}`
})

const canNavigateUp = computed(() => parentPath.value !== null)

const filteredItems = computed(() => {
  let result = items.value.slice()
  
  // 搜索过滤
  if (searchKeyword.value) {
    const keyword = searchKeyword.value.toLowerCase()
    result = result.filter(item => item.name.toLowerCase().includes(keyword))
  }
  
  // 排序:目录在前,文件在后, 然后根据选择的排序方式排序
  result.sort((a, b) => {
    // 始终让目录排在前面
    if (a.isDir !== b.isDir) {
      return a.isDir ? -1 : 1
    }
    
    // 如果都是目录或都是文件，则应用排序规则
    let comparison = 0
    
    if (sortBy.value === 'time') {
      const timeA = a.modTime ? new Date(a.modTime).getTime() : 0
      const timeB = b.modTime ? new Date(b.modTime).getTime() : 0
      comparison = timeA - timeB
    } else {
      comparison = a.name.localeCompare(b.name)
    }
    
    return sortDesc.value ? -comparison : comparison
  })
  
  return result
})

const paginatedItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return filteredItems.value.slice(start, end)
})

// 文件类型判断
function isImage(filename: string): boolean {
  const imageExts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico']
  return imageExts.some(ext => filename.toLowerCase().endsWith(ext))
}

function isVideo(filename: string): boolean {
  const videoExts = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v']
  return videoExts.some(ext => filename.toLowerCase().endsWith(ext))
}

function getVideoType(filename: string | undefined): string {
  if (!filename) return ''
  const parts = filename.split('.')
  if (parts.length < 2) return ''
  const ext = parts.pop()?.toLowerCase()
  
  if (ext === 'mkv') return 'video/x-matroska' // video.js might need specific type for mkv if supported, or just let browser handle
  // For common formats:
  if (ext === 'mp4') return 'video/mp4'
  if (ext === 'webm') return 'video/webm'
  if (ext === 'ogg') return 'video/ogg'
  return ''
}

// 缩略图URL响应式存储
const thumbnailUrls = ref<Record<string, string>>({})
// 缩略图加载队列
const thumbnailQueue = ref<DriveItem[]>([])
const isProcessingQueue = ref(false)

// 获取缩略图URL - 返回响应式的URL
function getThumbnailUrl(item: DriveItem): string {
  const cacheKey = `${currentRemote.value}:${item.path}`
  return thumbnailUrls.value[cacheKey] || ''
}

// 处理缩略图队列
async function processThumbnailQueue() {
  if (isProcessingQueue.value || thumbnailQueue.value.length === 0) return
  
  isProcessingQueue.value = true
  
  try {
    while (thumbnailQueue.value.length > 0) {
      // 取出第一个任务（已按时间排序）
      const item = thumbnailQueue.value.shift()
      if (!item) continue
      
      const cacheKey = `${currentRemote.value}:${item.path}`
      
      // 如果已有缓存，跳过
      if (thumbnailUrls.value[cacheKey]) continue
      
      const remoteInfo = availableRemotes.value.find(r => r.name === currentRemote.value)
      const remoteType = remoteInfo?.type || 'onedrive'
      
      try {
        console.log('正在加载缩略图:', item.name)
        const response = await getThumbnail(currentRemote.value, item.path, remoteType, currentPath.value, item.id || '')
        
        if (response.success && response.thumbnail_url) {
          thumbnailUrls.value = {
            ...thumbnailUrls.value,
            [cacheKey]: response.thumbnail_url
          }
        }
      } catch (err) {
        console.error('获取缩略图失败:', item.name, err)
      }
      
      // 稍微延迟一下，给浏览器喘息机会，也避免请求过于密集
      await new Promise(resolve => setTimeout(resolve, 100))
    }
  } finally {
    isProcessingQueue.value = false
  }
}

// 将当前页面的图片/视频添加到加载队列
function queueThumbnails() {
  if (viewMode.value !== 'grid') return
  
  const itemsToLoad = paginatedItems.value.filter(item => {
    if (item.isDir) return false
    if (!isImage(item.name) && !isVideo(item.name)) return false
    
    const cacheKey = `${currentRemote.value}:${item.path}`
    return !thumbnailUrls.value[cacheKey]
  })
  
  // 按修改时间降序排序（最新的优先）
  itemsToLoad.sort((a, b) => {
    let timeA = 0
    let timeB = 0
    
    if (a.modTime) {
      const t = new Date(a.modTime).getTime()
      if (!isNaN(t)) timeA = t
    }
    
    if (b.modTime) {
      const t = new Date(b.modTime).getTime()
      if (!isNaN(t)) timeB = t
    }
    
    return timeB - timeA
  })
  
  if (itemsToLoad.length > 0) {
    console.log('Thumbnail queue sorted (desc). First:', itemsToLoad[0].name, itemsToLoad[0].modTime)
    console.log('Last:', itemsToLoad[itemsToLoad.length-1].name, itemsToLoad[itemsToLoad.length-1].modTime)
  }
  
  // 更新队列：保留不在新列表中的旧任务（可选），这里简单起见，直接用新页面的任务覆盖
  // 或者追加到队首？用户说"优先日期加载最新"，通常是指当前视图的最新。
  // 为了响应分页变化，我们应该优先加载当前可视区域的内容。
  
  // 策略：清空旧队列，只加载当前页面的任务，确保当前页面优先
  thumbnailQueue.value = itemsToLoad
  
  processThumbnailQueue()
}




// 加载 remotes 列表
async function loadRemotes() {
  try {
    const response = await getRcloneRemotes()
    if (response.success && response.remotes) {
      availableRemotes.value = response.remotes
      if (response.remotes.length > 0 && !currentRemote.value) {
        currentRemote.value = response.remotes[0].name
      }
    }
  } catch (err) {
    console.error('加载 remotes 失败:', err)
    ElMessage.error('加载云存储列表失败')
  }
}

async function fetchRemoteUsage(remote: string, force = false, showError = false) {
  if (!remote) return null

  const currentState = remoteUsageStates.value[remote]
  if (!force && currentState?.response) {
    return currentState.response
  }
  if (currentState?.loading) {
    return currentState.response || null
  }

  remoteUsageStates.value = {
    ...remoteUsageStates.value,
    [remote]: {
      response: currentState?.response,
      loading: true
    }
  }

  try {
    const response = await getDriveUsage(remote)
    remoteUsageStates.value = {
      ...remoteUsageStates.value,
      [remote]: {
        response,
        loading: false
      }
    }
    if (!response.success && showError) {
      ElMessage.error(response.error || '获取网盘容量失败')
    }
    return response
  } catch (err: any) {
    console.error('加载网盘容量失败:', err)
    const response: DriveUsageResponse = {
      success: false,
      supported: false,
      remote,
      error: err.message || '获取网盘容量失败'
    }
    remoteUsageStates.value = {
      ...remoteUsageStates.value,
      [remote]: {
        response,
        loading: false
      }
    }
    if (showError) {
      ElMessage.error(err.message || '获取网盘容量失败')
    }
    return response
  }
}

async function preloadRemoteUsages() {
  const tasks = availableRemotes.value.map(remote => fetchRemoteUsage(remote.name))
  await Promise.allSettled(tasks)
}

async function loadDriveUsage(force = false, showError = false) {
  if (!currentRemote.value) return
  await fetchRemoteUsage(currentRemote.value, force, showError)
}

function getRemoteUsagePercent(remote: string): number | null {
  const usage = remoteUsageStates.value[remote]?.response
  const total = usage?.data?.total
  const used = usage?.data?.used
  if (!usage?.supported || !total || used === undefined || used === null || total <= 0) return null
  return Math.min(100, (used / total) * 100)
}

function getRemoteUsageSummary(remote: string): string {
  const state = remoteUsageStates.value[remote]
  if (state?.loading) return '容量读取中...'
  const usage = state?.response
  if (!usage) return '等待加载容量'
  if (!usage.success) return '容量读取失败'
  if (!usage.supported || !usage.data) return '暂不支持容量统计'

  const used = formatBytes(usage.data.used ?? 0)
  const total = formatBytes(usage.data.total ?? 0)
  return `${used} / ${total}`
}

// 浏览目录
async function browse() {
  if (!currentRemote.value) return

  loading.value = true
  try {
    const response = await browseDrive(currentRemote.value, currentPath.value)
    if (response.success && response.items) {
      items.value = response.items
      // 重置分页
      currentPage.value = 1
    } else {
      ElMessage.error(response.error || '获取文件列表失败')
      items.value = []
    }
  } catch (err: any) {
    console.error('浏览失败:', err)
    ElMessage.error(err.message || '获取文件列表失败')
    items.value = []
  } finally {
    loading.value = false
  }
}

// Remote 改变
function handleRemoteChange() {
  currentPath.value = '/'
  if (!remoteUsageStates.value[currentRemote.value]?.response) {
    loadDriveUsage()
  }
  browse()
}

// 下载文件
async function handleDownload(item: DriveItem) {
  if (item.isDir) return
  
  const url = buildAuthorizedApiUrl('/api/rclone/file', {
    remote: currentRemote.value,
    path: item.path,
    download: true,
  })

  window.open(url, '_blank')
}

// 删除文件
function handleDelete(item: DriveItem) {
  ElMessageBox.confirm(
    `确定要删除 ${item.isDir ? '文件夹' : '文件'} "${item.name}" 吗？此操作不可恢复。`,
    '确认删除',
    {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    }
  ).then(async () => {
    loading.value = true
    try {
      const response = await deleteFile(currentRemote.value, item.path, item.isDir)
      if (response.success) {
        ElMessage.success('删除成功')
        // 刷新列表
        browse()
      } else {
        ElMessage.error(response.error || '删除失败')
      }
    } catch (err: any) {
      console.error('删除失败:', err)
      ElMessage.error(err.message || '删除失败')
    } finally {
      loading.value = false
    }
  }).catch(() => {
    // 取消删除
  })
}

// 预览状态
const showPreview = ref(false)
const previewItem = ref<DriveItem | null>(null)
const previewType = ref<'image' | 'video' | 'unknown'>('unknown')
const previewUrl = ref('')
const previewLoading = ref(false)
const downloadingPaths = ref<Record<string, boolean>>({})
let previewRequestToken = 0

function preparePreviewSource(row: DriveItem): string {
  return buildAuthorizedApiUrl('/api/rclone/file', {
    remote: currentRemote.value,
    path: row.path,
  })
}

// 点击行
function handleRowClick(row: DriveItem) {
  if (row.isDir) {
    // 进入目录
    navigateToPath(row.path)
  } else {
    // 预览文件
    if (isImage(row.name)) {
      previewType.value = 'image'
      previewItem.value = row
      previewUrl.value = preparePreviewSource(row)
      showPreview.value = true
    } else if (isVideo(row.name)) {
      previewType.value = 'video'
      previewItem.value = row
      previewUrl.value = preparePreviewSource(row)
      showPreview.value = true
    } else {
      ElMessage.info('暂不支持预览此类型文件')
    }
  }
}

// 关闭预览
function closePreview() {
  previewRequestToken += 1
  showPreview.value = false
  previewItem.value = null
  previewUrl.value = ''
  previewType.value = 'unknown'
  previewLoading.value = false
}

// 导航到路径
function navigateToPath(path: string) {
  currentPath.value = path || '/'
  browse()
}

function navigateUp() {
  if (!parentPath.value) return
  navigateToPath(parentPath.value)
}

// 导航到面包屑某一段
function navigateToSegment(index: number) {
  const segments = pathSegments.value.slice(0, index + 1)
  navigateToPath('/' + segments.join('/'))
}

// 格式化文件大小
function formatBytes(bytes: number | undefined): string {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function formatCount(value: number | undefined | null): string {
  if (value === undefined || value === null) return '-'
  return new Intl.NumberFormat('zh-CN').format(value)
}

// 格式化日期
function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return '-'
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('zh-CN')
  } catch {
    return '-'
  }
}

onMounted(async () => {
  await loadRemotes()
  if (currentRemote.value) {
    void preloadRemoteUsages()
    browse()
  }
})

// 监听视图模式变化
watch(viewMode, (newMode) => {
  if (newMode === 'grid') {
    queueThumbnails()
  }
})

// 监听分页数据变化
watch(paginatedItems, () => {
    queueThumbnails()
}, { deep: true })

</script>

<style scoped>
.drive-page {
  padding: 20px;
}

.drive-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.drive-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.drive-header-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: #64748b;
}

.drive-header-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.header-remote-select {
  width: 220px;
}

.header-remote-select :deep(.el-select__wrapper) {
  min-height: 38px;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: none;
  border: 1px solid #dbeafe;
}

.header-usage {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 10px;
  background: linear-gradient(135deg, #f8fafc 0%, #eef6ff 100%);
  border: 1px solid #dbeafe;
}

.header-usage-name {
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
}

.header-usage-text {
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
}

.drive-topbar {
  margin-bottom: 12px;
}

.drive-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.drive-breadcrumb-card {
  flex: 1;
  min-width: 240px;
}

.drive-nav-button {
  flex: 0 0 auto;
}

.drive-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.view-mode-toggle :deep(.el-button) {
  border-radius: 10px;
}

.sort-select {
  width: 152px;
}

.search-input {
  width: 260px;
}

.remote-option {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 2px 0;
}

.remote-option-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.remote-option-name {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}

.remote-option-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 11px;
  color: #64748b;
}

.remote-option-percent {
  padding: 1px 6px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 600;
}

.file-name {
  display: flex;
  align-items: center;
}

.el-breadcrumb :deep(.el-breadcrumb__item) {
  cursor: pointer;
}

.el-breadcrumb :deep(.el-breadcrumb__inner):hover {
  color: var(--el-color-primary);
}

.pagination-container {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}

/* 网格视图样式 */
.grid-view {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 16px;
  margin-top: 20px;
  padding: 8px;
}

.grid-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  cursor: pointer;
  transition: all 0.3s;
  background: white;
}

.grid-item:hover {
  border-color: var(--el-color-primary);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
  transform: translateY(-2px);
}

.grid-item-preview {
  width: 100%;
  height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
  border-radius: 6px;
  overflow: hidden;
  position: relative;
}

.grid-icon {
  color: #909399;
}

.grid-thumbnail {
  width: 100%;
  height: 100%;
}

.image-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}

.video-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.video-placeholder .el-icon {
  color: white;
}

.grid-video {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.grid-video .grid-thumbnail {
  width: 100%;
  height: 100%;
}

.grid-video .grid-icon {
  color: white;
}

.video-badge {
  position: absolute;
  bottom: 8px;
  right: 8px;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.grid-item-name {
  margin-top: 8px;
  font-size: 14px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.grid-item-info {
  margin-top: 4px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 24px;
}

.grid-item-size {
  font-size: 12px;
  color: #909399;
}

.grid-item-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}

.grid-item:hover .grid-item-actions {
  opacity: 1;
}

.video-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 420px;
  background: #000;
  border-radius: 4px;
  overflow: hidden;
}

:deep(.drive-remote-popper .el-select-dropdown__item) {
  height: auto;
  min-height: 52px;
  padding-top: 6px;
  padding-bottom: 6px;
  line-height: 1.4;
}

@media (max-width: 960px) {
  .drive-actions {
    width: 100%;
  }

  .header-remote-select {
    width: 100%;
  }

  .sort-select,
  .search-input {
    width: 100%;
  }
}
</style>
