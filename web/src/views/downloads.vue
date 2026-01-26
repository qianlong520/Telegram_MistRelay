<template>
  <div class="downloads-page">
    <el-card shadow="hover">
      <template #header>
        <div class="flex justify-between items-center">
          <span>下载记录</span>
          <div class="flex gap-4 items-center">
            <el-select v-model="limit" @change="fetchDownloads" style="width: 150px">
              <el-option label="显示 50 条" :value="50" />
              <el-option label="显示 100 条" :value="100" />
              <el-option label="显示 200 条" :value="200" />
              <el-option label="显示 500 条" :value="500" />
            </el-select>
            <el-button @click="fetchDownloads" :icon="Refresh" type="primary" size="small">
              刷新
            </el-button>
            <el-button @click="autoRefresh = !autoRefresh" :type="autoRefresh ? 'primary' : ''" size="small">
              {{ autoRefresh ? '停止自动刷新' : '开启自动刷新' }}
            </el-button>
          </div>
        </div>
      </template>
      
      <el-skeleton v-if="isLoading" :rows="10" animated />
      
      <el-alert
        v-else-if="error"
        :title="`加载失败: ${error}`"
        type="error"
        :closable="false"
      >
        <template #default>
          <el-button @click="fetchDownloads" type="primary" class="mt-2">重试</el-button>
        </template>
      </el-alert>
      
      <div v-else-if="groups && groups.length > 0" class="download-groups">
        <el-collapse v-model="activeGroups" accordion>
          <el-collapse-item
            v-for="group in groups"
            :key="group.group_key"
            :name="group.group_key"
            class="download-group-item"
          >
            <template #title>
              <div class="group-header">
                <div class="group-info">
                  <el-icon class="group-icon"><Files /></el-icon>
                  <div class="group-details">
                    <div class="group-title">
                      <span v-if="group.caption" class="caption">{{ truncateText(group.caption, 50) }}</span>
                      <span v-else class="group-type">
                        {{ group.group_type === 'media_group' ? '媒体组' : '消息' }}
                        <span v-if="group.message_id">#{{ group.message_id }}</span>
                      </span>
                    </div>
                    <div class="group-meta">
                      <el-tag size="small" type="info">{{ group.stats.total_files }} 个文件</el-tag>
                      <el-tag size="small" type="success">{{ group.stats.completed }} 已完成</el-tag>
                      <el-tag v-if="group.stats.downloading > 0" size="small" type="warning">
                        {{ group.stats.downloading }} 下载中
                      </el-tag>
                      <el-tag v-if="group.stats.failed > 0" size="small" type="danger">
                        {{ group.stats.failed }} 失败
                      </el-tag>
                      <span class="group-date">{{ formatDate(group.message_date || group.created_at) }}</span>
                    </div>
                  </div>
                </div>
                <div class="group-progress">
                  <el-progress
                    :percentage="getGroupProgress(group.stats)"
                    :status="getGroupStatus(group.stats)"
                    :stroke-width="6"
                    style="width: 120px"
                  />
                  <span class="group-size">{{ formatSize(group.stats.total_size) }}</span>
                </div>
              </div>
            </template>
            
            <div class="group-downloads">
              <el-table :data="group.downloads" stripe size="small" style="width: 100%">
                <el-table-column prop="file_name" label="文件名" min-width="250" show-overflow-tooltip>
                  <template #default="{ row }">
                    <div class="file-info">
                      <el-icon class="file-icon"><Document /></el-icon>
                      <span>{{ row.file_name || row.source_url?.substring(0, 40) || '未知文件' }}</span>
                    </div>
                  </template>
                </el-table-column>
                
                <el-table-column label="大小" width="120">
                  <template #default="{ row }">
                    {{ formatSize(row.total_length || row.file_size) }}
                  </template>
                </el-table-column>
                
                <el-table-column label="状态" width="100">
                  <template #default="{ row }">
                    <el-tag :type="getStatusTagType(row.status)" size="small">
                      {{ getStatusText(row.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                
                <el-table-column label="进度" width="150">
                  <template #default="{ row }">
                    <el-progress
                      :percentage="getProgress(row.total_length, row.completed_length, row.status)"
                      :status="getProgressStatus(row.status)"
                      :stroke-width="6"
                    />
                  </template>
                </el-table-column>
                
                <el-table-column label="速度" width="100">
                  <template #default="{ row }">
                    <span v-if="row.status === 'downloading'">{{ formatSpeed(row.download_speed) }}</span>
                    <span v-else>-</span>
                  </template>
                </el-table-column>
                
                <el-table-column label="创建时间" width="160">
                  <template #default="{ row }">
                    {{ formatDate(row.created_at) }}
                  </template>
                </el-table-column>
                
                <el-table-column label="操作" width="120" fixed="right">
                  <template #default="{ row }">
                    <el-button-group>
                      <el-button
                        v-if="row.status === 'downloading'"
                        size="small"
                        :icon="VideoPause"
                        @click="handlePause(row)"
                        title="暂停"
                      />
                      <el-button
                        v-if="row.status === 'pending'"
                        size="small"
                        :icon="VideoPlay"
                        @click="handleResume(row)"
                        title="恢复"
                      />
                      <el-button
                        size="small"
                        type="danger"
                        :icon="Delete"
                        @click="handleDelete(row)"
                        title="删除"
                      />
                    </el-button-group>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-collapse-item>
        </el-collapse>
        
        <div class="mt-4 text-center text-gray-600">
          共 {{ groups.length }} 个消息组，{{ totalDownloads }} 个下载任务
        </div>
      </div>
      
      <el-empty v-else description="暂无下载记录" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Files, Document, VideoPause, VideoPlay, Delete } from '@element-plus/icons-vue'
import { useIntervalFn } from '@vueuse/core'
import { getDownloads } from '@/api'
import type { DownloadGroup } from '@/types/api'
import {
  formatSize,
  formatDate,
  getProgress,
  getStatusText,
  getStatusTagType
} from '@/utils/formatters'

const groups = ref<DownloadGroup[]>([])
const isLoading = ref(true)
const error = ref<string | null>(null)
const limit = ref(100)
const autoRefresh = ref(false)
const activeGroups = ref<string[]>([])

const totalDownloads = computed(() => {
  return groups.value.reduce((sum, group) => sum + group.stats.total_files, 0)
})

function fetchDownloads() {
  isLoading.value = true
  error.value = null
  getDownloads(limit.value, true)
    .then(response => {
      if (response.success && response.grouped) {
        groups.value = (response.data as DownloadGroup[]) || []
        // 默认展开第一个组
        if (groups.value.length > 0 && activeGroups.value.length === 0) {
          activeGroups.value = [groups.value[0].group_key]
        }
      } else {
        error.value = '获取数据失败'
      }
    })
    .catch(err => {
      error.value = err.message || '未知错误'
      console.error('获取下载记录失败:', err)
    })
    .finally(() => {
      isLoading.value = false
    })
}

function getGroupProgress(stats: DownloadGroup['stats']): number {
  if (stats.total_size === 0) return 0
  return Math.round((stats.completed_size / stats.total_size) * 100)
}

function getGroupStatus(stats: DownloadGroup['stats']): 'success' | 'exception' | 'warning' {
  if (stats.failed > 0) return 'exception'
  if (stats.downloading > 0 || stats.pending > 0) return 'warning'
  return 'success'
}

function truncateText(text: string, maxLength: number): string {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength) + '...'
}

function formatSpeed(speed?: number): string {
  if (!speed) return '-'
  return formatSize(speed) + '/s'
}

function getProgressStatus(status?: string): 'success' | 'exception' | 'warning' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  return 'warning'
}

function handlePause(_task: any) {
  ElMessage.info('暂停功能需要后端API支持')
}

function handleResume(_task: any) {
  ElMessage.info('恢复功能需要后端API支持')
}

function handleDelete(task: any) {
  ElMessageBox.confirm(
    `确定要删除任务 "${task.file_name || '未知文件'}" 吗？`,
    '确认删除',
    {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    }
  ).then(() => {
    ElMessage.info('删除功能需要后端API支持')
    fetchDownloads()
  }).catch(() => {})
}

// 自动刷新定时器
const { pause, resume, isActive } = useIntervalFn(fetchDownloads, 10000, { immediate: false })

// 监听自动刷新状态
watch(autoRefresh, (enabled) => {
  if (enabled) {
    resume()
  } else {
    pause()
  }
})

// 组件卸载时停止自动刷新
onUnmounted(() => {
  pause()
})

onMounted(() => {
  fetchDownloads()
})
</script>

<style scoped>
.downloads-page {
  @apply space-y-8;
  animation: fadeIn 0.5s ease-out;
}

.page-header {
  @apply mb-8;
  animation: slideInLeft 0.6s ease-out;
}

.page-title {
  @apply text-4xl font-bold mb-3;
  position: relative;
  display: inline-block;
}

.title-text {
  background: linear-gradient(135deg, #1f2937 0%, #667eea 50%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  position: relative;
  z-index: 1;
}

.title-decoration {
  position: absolute;
  bottom: -8px;
  left: 0;
  width: 80px;
  height: 4px;
  background: var(--gradient-primary);
  border-radius: 2px;
  animation: slideInLeft 0.8s ease-out 0.2s both;
}

.page-subtitle {
  @apply text-gray-600 text-base;
  font-weight: 500;
}

.downloads-page :deep(.el-card) {
  border-radius: 16px;
  border: 1px solid rgba(229, 231, 235, 0.8);
  transition: all 0.3s ease;
  overflow: hidden;
}

.downloads-page :deep(.el-card:hover) {
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.08);
  border-color: rgba(102, 126, 234, 0.2);
}

.downloads-page :deep(.el-card__header) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(249, 250, 251, 0.9));
  border-bottom: 1px solid rgba(229, 231, 235, 0.8);
  padding: 20px 24px;
}

.download-groups {
  @apply space-y-3;
}

.download-group-item {
  @apply mb-3;
  animation: scaleIn 0.3s ease-out;
}

:deep(.el-collapse-item) {
  border-radius: 12px;
  border: 1px solid rgba(229, 231, 235, 0.8);
  overflow: hidden;
  margin-bottom: 12px;
  transition: all 0.3s ease;
}

:deep(.el-collapse-item:hover) {
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.1);
  border-color: rgba(102, 126, 234, 0.3);
}

:deep(.el-collapse-item__header) {
  @apply px-5 py-4;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95), rgba(249, 250, 251, 0.95));
  border-bottom: 1px solid rgba(229, 231, 235, 0.5);
  transition: all 0.3s ease;
  font-weight: 500;
}

:deep(.el-collapse-item__header:hover) {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.05), rgba(118, 75, 162, 0.03));
}

:deep(.el-collapse-item__content) {
  @apply px-5 pb-5;
  background: rgba(249, 250, 251, 0.3);
}

.group-header {
  @apply flex items-center justify-between w-full pr-4;
}

.group-info {
  @apply flex items-center gap-4 flex-1;
}

.group-icon {
  color: #667eea;
  @apply text-2xl;
  transition: all 0.3s ease;
}

:deep(.el-collapse-item__header:hover) .group-icon {
  transform: scale(1.1) rotate(5deg);
}

.group-details {
  @apply flex-1;
}

.group-title {
  @apply font-semibold text-gray-900 mb-2;
  font-size: 16px;
}

.caption {
  @apply text-gray-800;
}

.group-type {
  @apply text-gray-600;
}

.group-meta {
  @apply flex items-center gap-2 flex-wrap;
}

.group-meta :deep(.el-tag) {
  border-radius: 6px;
  font-weight: 500;
  border: none;
}

.group-date {
  @apply text-xs text-gray-500 ml-2;
  font-weight: 500;
}

.group-progress {
  @apply flex items-center gap-4;
}

.group-size {
  @apply text-sm text-gray-700 font-semibold;
  min-width: 80px;
  text-align: right;
}

.group-downloads {
  @apply mt-5;
}

.group-downloads :deep(.el-table) {
  border-radius: 8px;
  overflow: hidden;
}

.group-downloads :deep(.el-table__row) {
  transition: all 0.2s ease;
}

.group-downloads :deep(.el-table__row:hover) {
  background: linear-gradient(90deg, rgba(102, 126, 234, 0.05), rgba(118, 75, 162, 0.03));
}

.file-info {
  @apply flex items-center gap-2;
}

.file-icon {
  color: #667eea;
  transition: all 0.2s ease;
}

.group-downloads :deep(.el-table__row:hover) .file-icon {
  transform: scale(1.1);
}

/* 进度条美化 */
:deep(.el-progress__text) {
  @apply font-semibold;
}

:deep(.el-progress-bar__outer) {
  border-radius: 10px;
  overflow: hidden;
}

:deep(.el-progress-bar__inner) {
  border-radius: 10px;
  transition: all 0.3s ease;
}

/* 按钮美化 */
:deep(.el-button) {
  border-radius: 8px;
  transition: all 0.2s ease;
  font-weight: 500;
}

:deep(.el-button:hover) {
  transform: translateY(-1px);
}

:deep(.el-button-group .el-button) {
  border-radius: 6px;
}

/* 选择器美化 */
:deep(.el-select) {
  border-radius: 8px;
}

:deep(.el-input__wrapper) {
  border-radius: 8px;
  transition: all 0.2s ease;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.1);
}
</style>
