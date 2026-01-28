<template>
  <div class="tasks-center-page">
    <el-card shadow="hover">
      <template #header>
        <div class="flex justify-between items-center">
          <span class="text-xl font-semibold">任务中心</span>
          <div class="flex gap-4 items-center">
            <el-select v-model="limit" @change="handleLimitChange" style="width: 150px">
              <el-option label="显示 50 条" :value="50" />
              <el-option label="显示 100 条" :value="100" />
              <el-option label="显示 200 条" :value="200" />
              <el-option label="显示 500 条" :value="500" />
            </el-select>
            <el-button @click="handleRefresh" :icon="Refresh" type="primary" size="small">
              刷新
            </el-button>
            <el-button @click="handleDeleteAll" :icon="Delete" type="danger" size="small">
              删除所有记录
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
          <el-button @click="handleRefresh" type="primary" class="mt-2">重试</el-button>
        </template>
      </el-alert>
      
      <div v-else-if="groups && groups.length > 0" class="tasks-tabs-container">
        <el-tabs v-model="activeTab" class="tasks-tabs">
          <!-- 下载标签页 -->
          <el-tab-pane name="download">
            <template #label>
              <span class="flex items-center gap-2">
                <el-icon><Download /></el-icon>
                下载
                <el-tag v-if="activeDownloads.length > 0" size="small" type="warning">{{ activeDownloads.length }}</el-tag>
              </span>
            </template>

            <el-empty v-if="activeDownloads.length === 0" description="当前没有正在下载/等待的任务" :image-size="80" />
            <div v-else>
              <el-table
                :data="activeDownloads"
                stripe
                size="small"
                style="width: 100%"
                row-key="id"
                @row-click="openGroupForActiveRow"
              >
                <el-table-column prop="group_title" label="来源" min-width="220" show-overflow-tooltip />

                <el-table-column prop="file_name" label="文件名" min-width="260" show-overflow-tooltip>
                  <template #default="{ row }">
                    <div class="file-info">
                      <el-icon class="file-icon"><Document /></el-icon>
                      <span>{{ row.file_name || row.source_url?.substring(0, 40) || '未知文件' }}</span>
                    </div>
                  </template>
                </el-table-column>

                <el-table-column label="状态" width="120">
                  <template #default="{ row }">
                    <el-tag :type="getStatusTagTypeWithSkip(row.status, row.error_message)" size="small">
                      {{ getStatusTextWithSkip(row.status, row.error_message) }}
                    </el-tag>
                  </template>
                </el-table-column>

                <el-table-column label="进度" width="180">
                  <template #default="{ row }">
                    <el-progress
                      :percentage="getProgress(row.total_length, row.completed_length, row.status)"
                      :status="getProgressStatus(row.status)"
                      :stroke-width="6"
                    />
                  </template>
                </el-table-column>

                <el-table-column label="速度" width="110">
                  <template #default="{ row }">
                    <span v-if="row.status === 'downloading'">{{ formatSpeed(row.download_speed) }}</span>
                    <span v-else>-</span>
                  </template>
                </el-table-column>

                <el-table-column label="更新时间" width="160">
                  <template #default="{ row }">
                    {{ formatDate(row.updated_at || row.created_at) }}
                  </template>
                </el-table-column>
              </el-table>
              <div class="mt-2 text-xs text-gray-500">
                提示：点击任意行会自动切换到“全部”并展开对应消息组
              </div>
            </div>
          </el-tab-pane>

          <!-- 上传标签页 -->
          <el-tab-pane name="upload">
            <template #label>
              <span class="flex items-center gap-2">
                <el-icon><Upload /></el-icon>
                上传
                <el-tag v-if="activeUploads.length > 0" size="small" type="warning">{{ activeUploads.length }}</el-tag>
              </span>
            </template>
            
            <el-empty v-if="activeUploads.length === 0" description="当前没有正在上传的任务" :image-size="80" />
            <div v-else>
              <el-table :data="activeUploads" stripe size="small" style="width: 100%" row-key="id">
                <el-table-column prop="file_name" label="文件名" min-width="250" show-overflow-tooltip>
                  <template #default="{ row }">
                    <div class="file-info">
                      <el-icon class="file-icon"><Document /></el-icon>
                      <span>{{ row.file_name || '未知文件' }}</span>
                    </div>
                  </template>
                </el-table-column>
                
                <el-table-column label="上传目标" width="120">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.upload_target === 'onedrive' ? 'primary' : 'success'">
                      {{ row.upload_target === 'onedrive' ? 'OneDrive' : row.upload_target === 'telegram' ? 'Telegram' : row.upload_target }}
                    </el-tag>
                  </template>
                </el-table-column>
                
                <el-table-column label="状态" width="120">
                  <template #default="{ row }">
                    <el-tag :type="getUploadStatusTagType(row.status)" size="small">
                      {{ getUploadStatusText(row.status, row.upload_target) }}
                    </el-tag>
                  </template>
                </el-table-column>
                
                <el-table-column label="进度" width="180">
                  <template #default="{ row }">
                    <el-progress
                      :percentage="getUploadProgress(row.total_size, row.uploaded_size)"
                      :status="row.status === 'failed' ? 'exception' : row.status === 'completed' ? 'success' : 'warning'"
                      :stroke-width="6"
                    />
                  </template>
                </el-table-column>
                
                <el-table-column label="速度" width="110">
                  <template #default="{ row }">
                    <span v-if="row.status === 'uploading' && row.upload_speed && row.upload_speed > 0">
                      {{ formatSpeed(row.upload_speed) }}
                    </span>
                    <span v-else-if="row.status === 'uploading'">计算中...</span>
                    <span v-else>-</span>
                  </template>
                </el-table-column>
                
                <el-table-column label="大小" width="120">
                  <template #default="{ row }">
                    {{ formatSize(row.total_size) }}
                  </template>
                </el-table-column>
                
                <el-table-column label="更新时间" width="160">
                  <template #default="{ row }">
                    {{ formatDate(row.updated_at || row.created_at) }}
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-tab-pane>

          <!-- 记录标签页 -->
          <el-tab-pane name="records">
            <template #label>
              <span class="flex items-center gap-2">
                <el-icon><Files /></el-icon>
                记录
                <el-tag size="small" type="info">{{ groups.length }}</el-tag>
              </span>
            </template>

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
                          <el-tag v-if="(group.stats.skipped || 0) > 0" size="small" type="info">
                            {{ group.stats.skipped }} 已跳过
                          </el-tag>
                          <el-tag v-if="group.stats.failed > 0" size="small" type="danger">
                            {{ group.stats.failed }} 失败
                          </el-tag>
                          <span class="group-date">{{ formatDate(group.created_at || group.message_date) }}</span>
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
                  <el-table 
                    :data="group.downloads" 
                    stripe 
                    size="small" 
                    style="width: 100%"
                    row-key="id"
                    @row-click="handleRowClick"
                    class="cursor-pointer"
                  >
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
                    
                    <el-table-column label="状态" width="120">
                      <template #default="{ row }">
                        <el-tag 
                          :type="getRecordStatusTagType(row)" 
                          size="small"
                        >
                          {{ getRecordStatusText(row) }}
                        </el-tag>
                        <el-tooltip 
                          v-if="row.status === 'failed' && row.error_message && row.error_message.includes('跳过')"
                          :content="row.error_message"
                          placement="top"
                        >
                          <el-icon class="ml-1 cursor-pointer" style="color: #909399">
                            <InfoFilled />
                          </el-icon>
                        </el-tooltip>
                      </template>
                    </el-table-column>
                    
                    <el-table-column label="远程路径" min-width="200" show-overflow-tooltip>
                      <template #default="{ row }">
                        <div v-if="row.uploads && row.uploads.length > 0" class="space-y-1">
                          <div v-for="upload in row.uploads" :key="upload.id">
                            <span v-if="upload.remote_path" class="text-green-600">{{ upload.remote_path }}</span>
                            <span v-else class="text-gray-400">-</span>
                          </div>
                        </div>
                        <span v-else-if="row.remote_path" class="text-green-600">{{ row.remote_path }}</span>
                        <span v-else class="text-gray-400">-</span>
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
                            @click.stop="handlePause(row)"
                            title="暂停"
                          />
                          <el-button
                            v-if="row.status === 'pending'"
                            size="small"
                            :icon="VideoPlay"
                            @click.stop="handleResume(row)"
                            title="恢复"
                          />
                          <el-button
                            size="small"
                            type="danger"
                            :icon="Delete"
                            @click.stop="handleDelete(row)"
                            title="删除"
                          />
                        </el-button-group>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-tab-pane>
        </el-tabs>
      </div>
      
      <el-empty v-else-if="!isLoading && !error && (!groups || groups.length === 0)" description="暂无任务记录" />
    </el-card>
    
    <!-- 文件详情对话框 -->
    <el-dialog
      v-model="detailDialogVisible"
      title="文件详细信息"
      width="900px"
      :close-on-click-modal="true"
      :close-on-press-escape="true"
      class="file-detail-dialog"
      align-center
    >
      <div v-if="selectedRecord" class="file-detail-content">
        <el-descriptions :column="1" border class="detail-descriptions">
          <el-descriptions-item label="文件名">
            <div class="flex items-center gap-2">
              <el-icon><Document /></el-icon>
              <span>{{ selectedRecord.file_name || selectedRecord.source_url || '未知文件' }}</span>
            </div>
          </el-descriptions-item>
          
          <el-descriptions-item label="文件大小">
            {{ formatSize(selectedRecord.total_length || selectedRecord.file_size) }}
          </el-descriptions-item>
          
          <el-descriptions-item label="文件类型">
            <span v-if="selectedRecord.mime_type">{{ selectedRecord.mime_type }}</span>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>
          
          <el-descriptions-item label="下载状态">
            <el-tag 
              :type="getRecordStatusTagType(selectedRecord)" 
              size="small"
            >
              {{ getRecordStatusText(selectedRecord) }}
            </el-tag>
            <el-tooltip 
              v-if="selectedRecord.status === 'failed' && selectedRecord.error_message"
              :content="selectedRecord.error_message"
              placement="top"
            >
              <el-icon class="ml-1 cursor-pointer" style="color: #909399">
                <InfoFilled />
              </el-icon>
            </el-tooltip>
          </el-descriptions-item>
          
          <el-descriptions-item label="远程路径">
            <div v-if="selectedRecord.uploads && selectedRecord.uploads.length > 0" class="space-y-2">
              <div v-for="upload in selectedRecord.uploads" :key="upload.id" class="border-l-2 border-blue-500 pl-3">
                <div v-if="upload.remote_path" class="text-green-600 break-all">{{ upload.remote_path }}</div>
                <div v-else class="text-gray-400">-</div>
              </div>
            </div>
            <span v-else-if="selectedRecord.remote_path" class="text-green-600 break-all">{{ selectedRecord.remote_path }}</span>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>
          
          <el-descriptions-item label="上传状态" v-if="selectedRecord.uploads && selectedRecord.uploads.length > 0">
            <div class="space-y-2">
              <div v-for="upload in selectedRecord.uploads" :key="upload.id" class="flex items-center gap-2">
                <el-tag size="small" :type="upload.upload_target === 'onedrive' ? 'primary' : 'success'">
                  {{ upload.upload_target === 'onedrive' ? 'OneDrive' : upload.upload_target === 'telegram' ? 'Telegram' : upload.upload_target }}
                </el-tag>
                <el-tag 
                  :type="getUploadStatusTagType(upload.status)" 
                  size="small"
                >
                  {{ getUploadStatusText(upload.status, upload.upload_target) }}
                </el-tag>
                <span v-if="upload.completed_at" class="text-xs text-gray-500">
                  完成: {{ formatDate(upload.completed_at) }}
                </span>
                <span v-if="upload.error_message" class="text-xs text-red-500">
                  错误: {{ upload.error_message }}
                </span>
              </div>
            </div>
          </el-descriptions-item>
          
          <el-descriptions-item label="源TG URL">
            <div v-if="selectedRecord.chat_id && selectedRecord.message_id" class="flex items-center gap-2">
              <a 
                :href="getTelegramUrl(selectedRecord.chat_id, selectedRecord.message_id)" 
                target="_blank" 
                rel="noopener noreferrer"
                class="text-blue-600 hover:text-blue-800 break-all text-sm flex items-center gap-1 transition-colors"
              >
                {{ getTelegramUrl(selectedRecord.chat_id, selectedRecord.message_id) }}
                <el-icon class="text-xs ml-1"><Link /></el-icon>
              </a>
            </div>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>
          
          <el-descriptions-item label="源URL">
            <span v-if="selectedRecord.source_url" class="break-all text-sm">{{ selectedRecord.source_url }}</span>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>
          
          <el-descriptions-item label="说明文本">
            <span v-if="selectedRecord.caption" class="break-all">{{ selectedRecord.caption }}</span>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>
          
          <el-descriptions-item label="创建时间">
            {{ formatDate(selectedRecord.created_at) }}
          </el-descriptions-item>
          
          <el-descriptions-item label="开始时间">
            <span v-if="selectedRecord.started_at">{{ formatDate(selectedRecord.started_at) }}</span>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>
          
          <el-descriptions-item label="完成时间">
            <span v-if="selectedRecord.completed_at">{{ formatDate(selectedRecord.completed_at) }}</span>
            <span v-else class="text-gray-400">-</span>
          </el-descriptions-item>
          
          <el-descriptions-item label="更新时间">
            {{ formatDate(selectedRecord.updated_at || selectedRecord.created_at) }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
      
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="detailDialogVisible = false" type="primary">关闭</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Files, Document, VideoPause, VideoPlay, Delete, InfoFilled, Download, Upload, Link } from '@element-plus/icons-vue'
import { useIntervalFn } from '@vueuse/core'
import { getDownloads, deleteAllDownloads, getUploads, getConfig } from '@/api'
import type { DownloadGroup, DownloadRecord, UploadRecord } from '@/types/api'
import { wsClient } from '@/utils/websocket'
import {
  formatSize,
  formatDate,
  getProgress,
  getStatusText,
  getStatusTagType
} from '@/utils/formatters'

// 扩展状态文本和标签类型函数，支持跳过状态
function getStatusTextWithSkip(status?: string, errorMessage?: string): string {
  if (status === 'failed' && errorMessage && errorMessage.includes('跳过')) {
    return '已跳过'
  }
  return getStatusText(status)
}

function getStatusTagTypeWithSkip(status?: string, errorMessage?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'failed' && errorMessage && errorMessage.includes('跳过')) {
    return 'info'
  }
  return getStatusTagType(status)
}

// 根据下载、上传、清理状态综合判断记录状态
function getRecordStatusText(record: DownloadRecord): string {
  // 如果下载失败（包括跳过），显示失败状态
  if (record.status === 'failed') {
    if (record.error_message && record.error_message.includes('跳过')) {
      return '已跳过'
    }
    return '失败'
  }
  
  // 如果还在下载，显示下载中
  if (record.status === 'downloading' || record.status === 'pending') {
    return '下载中'
  }
  
  // 如果下载已完成，检查上传和清理状态
  if (record.status === 'completed') {
    // 如果有上传任务
    if (record.uploads && record.uploads.length > 0) {
      // 检查是否有正在上传的任务
      const hasUploading = record.uploads.some(u => 
        u.status === 'uploading' || u.status === 'pending' || u.status === 'waiting_download'
      )
      if (hasUploading) {
        return '上传中'
      }
      
      // 检查是否有失败的上传任务
      const hasFailed = record.uploads.some(u => u.status === 'failed')
      if (hasFailed) {
        // 如果还有未失败的上传任务，显示上传中；否则显示失败
        const hasCompleted = record.uploads.some(u => u.status === 'completed')
        return hasCompleted ? '上传中' : '失败'
      }
      
      // 检查所有上传是否都已完成
      const allCompleted = record.uploads.every(u => 
        u.status === 'completed' || u.status === 'failed'
      )
      
      if (allCompleted) {
        // 如果启用了自动清理，检查清理状态
        if (autoDeleteAfterUpload.value) {
          // 检查是否有未清理的已完成上传
          const hasUncleaned = record.uploads.some(u => 
            u.status === 'completed' && !u.cleaned_at
          )
          if (hasUncleaned) {
            return '清理中'
          }
        }
        // 所有上传都已完成，且（未启用自动清理 或 已清理），显示已完成
        return '已完成'
      }
      
      // 如果还有未完成的上传
      return '上传中'
    }
    
    // 没有上传任务，下载完成即完成
    return '已完成'
  }
  
  // 其他状态使用默认显示
  return getStatusText(record.status)
}

function getRecordStatusTagType(record: DownloadRecord): 'success' | 'warning' | 'danger' | 'info' {
  // 如果下载失败（包括跳过），显示失败状态
  if (record.status === 'failed') {
    if (record.error_message && record.error_message.includes('跳过')) {
      return 'info'
    }
    return 'danger'
  }
  
  // 如果还在下载，显示警告（进行中）
  if (record.status === 'downloading' || record.status === 'pending') {
    return 'warning'
  }
  
  // 如果下载已完成，检查上传和清理状态
  if (record.status === 'completed') {
    // 如果有上传任务
    if (record.uploads && record.uploads.length > 0) {
      // 检查是否有正在上传的任务
      const hasUploading = record.uploads.some(u => 
        u.status === 'uploading' || u.status === 'pending' || u.status === 'waiting_download'
      )
      if (hasUploading) {
        return 'warning'
      }
      
      // 检查是否有失败的上传任务
      const hasFailed = record.uploads.some(u => u.status === 'failed')
      if (hasFailed) {
        const hasCompleted = record.uploads.some(u => u.status === 'completed')
        return hasCompleted ? 'warning' : 'danger'
      }
      
      // 检查所有上传是否都已完成
      const allCompleted = record.uploads.every(u => 
        u.status === 'completed' || u.status === 'failed'
      )
      
      if (allCompleted) {
        // 如果启用了自动清理，检查清理状态
        if (autoDeleteAfterUpload.value) {
          // 检查是否有未清理的已完成上传
          const hasUncleaned = record.uploads.some(u => 
            u.status === 'completed' && !u.cleaned_at
          )
          if (hasUncleaned) {
            return 'warning' // 清理中
          }
        }
        // 所有上传都已完成，且（未启用自动清理 或 已清理），显示成功
        return 'success'
      }
      
      // 如果还有未完成的上传
      return 'warning'
    }
    
    // 没有上传任务，下载完成即完成
    return 'success'
  }
  
  // 其他状态使用默认显示
  return getStatusTagType(record.status)
}

const groups = ref<DownloadGroup[]>([])
const uploads = ref<UploadRecord[]>([])
const isLoading = ref(true)
const error = ref<string | null>(null)
const limit = ref(100)
const activeGroups = ref<string[]>([])
const activeTab = ref<'download' | 'upload' | 'records'>('download') // 默认显示"下载"标签页
const detailDialogVisible = ref(false)
const selectedRecord = ref<DownloadRecord | null>(null)
const autoDeleteAfterUpload = ref<boolean>(true) // 默认启用自动清理

// totalDownloads 已移除，不再需要

type ActiveDownloadRow = DownloadRecord & {
  group_key: string
  group_title: string
}

function getGroupTitle(group: DownloadGroup): string {
  if (group.caption) return truncateText(group.caption, 50)
  const typeText = group.group_type === 'media_group' ? '媒体组' : '消息'
  const msg = group.message_id ? ` #${group.message_id}` : ''
  return `${typeText}${msg}`
}

// 稳定的排序函数
function stableSortDownloads(a: ActiveDownloadRow, b: ActiveDownloadRow): number {
  // 使用创建时间戳和ID组合作为排序键，确保稳定
  const aTime = new Date(a.created_at || 0).getTime()
  const bTime = new Date(b.created_at || 0).getTime()
  if (aTime !== bTime) {
    return aTime - bTime  // 创建时间不同，按时间正序（先创建的在前，后创建的在后）
  }
  // 创建时间相同，按ID正序（确保排序稳定）
  return (a.id || 0) - (b.id || 0)
}

const activeDownloads = computed<ActiveDownloadRow[]>(() => {
  const rows: ActiveDownloadRow[] = []
  for (const group of groups.value) {
    for (const d of group.downloads || []) {
      if (d.status === 'downloading' || d.status === 'pending') {
        rows.push({
          ...d,
          group_key: group.group_key,
          group_title: getGroupTitle(group)
        })
      }
    }
  }

  // 使用稳定的排序函数，确保排序结果一致
  // 创建新数组并排序，避免修改原数组引用
  const sorted = [...rows]
  sorted.sort(stableSortDownloads)
  return sorted
})

function openGroupForActiveRow(row: ActiveDownloadRow) {
  activeTab.value = 'records'
  activeGroups.value = [row.group_key]
}

// 稳定的排序函数（上传）
function stableSortUploads(a: UploadRecord, b: UploadRecord): number {
  // 使用创建时间戳和ID组合作为排序键，确保稳定
  const aTime = new Date(a.created_at || 0).getTime()
  const bTime = new Date(b.created_at || 0).getTime()
  if (aTime !== bTime) {
    return aTime - bTime  // 创建时间不同，按时间正序（先创建的在前，后创建的在后）
  }
  // 创建时间相同，按ID正序（确保排序稳定）
  return (a.id || 0) - (b.id || 0)
}

// 计算正在上传的任务
const activeUploads = computed<UploadRecord[]>(() => {
  const filtered = uploads.value.filter(u => u.status === 'uploading' || u.status === 'pending' || u.status === 'waiting_download')
  // 使用稳定的排序函数，确保排序结果一致
  // 创建新数组并排序，避免修改原数组引用
  const sorted = [...filtered]
  sorted.sort(stableSortUploads)
  return sorted
})


function fetchUploads() {
  getUploads(limit.value)
    .then(response => {
      if (response.success) {
        uploads.value = response.data || []
      }
    })
    .catch(err => {
      console.error('获取上传记录失败:', err)
    })
}

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

function handleRefresh() {
  fetchDownloads()
  fetchUploads()
}

function handleLimitChange() {
  handleRefresh()
}

function getGroupProgress(stats: DownloadGroup['stats']): number {
  if (stats.total_size === 0) return 0
  return Math.round((stats.completed_size / stats.total_size) * 100)
}

function getGroupStatus(stats: DownloadGroup['stats']): 'success' | 'exception' | 'warning' {
  // 如果只有跳过的文件，不算异常
  const realFailed = (stats.failed || 0) - (stats.skipped || 0)
  if (realFailed > 0) return 'exception'
  if (stats.downloading > 0 || stats.pending > 0) return 'warning'
  return 'success'
}

function truncateText(text: string, maxLength: number): string {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength) + '...'
}

function formatSpeed(speed?: number): string {
  if (!speed || speed === 0) return '-'
  return formatSize(speed) + '/s'
}

function getProgressStatus(status?: string): 'success' | 'exception' | 'warning' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  return 'warning'
}

function getUploadStatusText(status?: string, target?: string): string {
  if (!status) return '未知'
  const statusMap: Record<string, string> = {
    'pending': '等待中',
    'waiting_download': '等待下载',
    'uploading': '上传中',
    'completed': '已完成',
    'failed': '失败',
    'cancelled': '已取消',
    'paused': '已暂停'
  }
  const statusText = statusMap[status] || status
  if (target && status === 'uploading') {
    const targetMap: Record<string, string> = {
      'onedrive': 'OneDrive',
      'telegram': 'Telegram'
    }
    return `${statusText} (${targetMap[target] || target})`
  }
  return statusText
}

function getUploadStatusTagType(status?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (!status) return 'info'
  if (status === 'completed') return 'success'
  if (status === 'uploading') return 'warning'
  if (status === 'failed' || status === 'cancelled') return 'danger'
  return 'info'
}

function getUploadProgress(totalSize?: number, uploadedSize?: number): number {
  if (!totalSize || totalSize === 0 || !uploadedSize) return 0
  return Math.round((uploadedSize / totalSize) * 100)
}

function getTelegramUrl(chatId?: number, messageId?: number): string {
  if (!chatId || !messageId) return ''
  // Telegram URL格式: https://t.me/c/{chat_id}/{message_id}
  // 对于频道和群组，chat_id需要去掉-100前缀
  let urlChatId = chatId.toString()
  if (urlChatId.startsWith('-100')) {
    urlChatId = urlChatId.substring(4)
  }
  return `https://t.me/c/${urlChatId}/${messageId}`
}

function handleRowClick(row: DownloadRecord) {
  selectedRecord.value = row
  detailDialogVisible.value = true
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

function handleDeleteAll() {
  ElMessageBox.confirm(
    '确定要删除所有记录吗？\n\n这将删除：\n• 所有下载记录\n• 所有上传记录\n• 所有清理记录\n• 所有媒体记录\n\n此操作不可恢复！',
    '确认删除所有记录',
    {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'warning',
      dangerouslyUseHTMLString: false
    }
  ).then(() => {
    deleteAllDownloads()
      .then(response => {
        if (response.success) {
          ElMessage.success(response.message || '已删除所有记录')
          fetchDownloads()
          fetchUploads()
        } else {
          ElMessage.error(response.error || '删除失败')
        }
      })
      .catch(err => {
        console.error('删除所有记录失败:', err)
        ElMessage.error('删除失败: ' + (err.message || '未知错误'))
      })
  }).catch(() => {})
}

// WebSocket 实时更新（优先使用）
let wsUnsubscribers: (() => void)[] = []

// 轮询定时器 - 作为 WebSocket 的备用方案，仅在 WebSocket 未连接时启用
const { pause, resume } = useIntervalFn(() => {
  fetchDownloads()
  fetchUploads()
}, 30000, { immediate: false })

// 检查 WebSocket 连接状态并管理轮询
function checkConnectionAndPoll() {
  if (!wsClient.isConnected()) {
    // WebSocket 未连接，启用轮询作为备用
    resume()
  } else {
    // WebSocket 已连接，停止轮询
    pause()
  }
}

// 组件卸载时清理
onUnmounted(() => {
  pause()
  // 取消 WebSocket 订阅
  wsUnsubscribers.forEach(unsub => unsub())
  wsUnsubscribers = []
})

onMounted(() => {
  // 获取配置，特别是 AUTO_DELETE_AFTER_UPLOAD
  getConfig('rclone')
    .then(response => {
      if (response.success && response.data?.rclone) {
        autoDeleteAfterUpload.value = response.data.rclone.AUTO_DELETE_AFTER_UPLOAD ?? true
      }
    })
    .catch(err => {
      console.error('获取配置失败:', err)
      // 使用默认值
      autoDeleteAfterUpload.value = true
    })
  
  fetchDownloads()
  fetchUploads()
  
  // 连接 WebSocket 并订阅更新
  wsClient.connect()
  
  // 订阅下载更新
  const unsubDownload = wsClient.on('download_update', (message) => {
    if (message.data) {
      // 更新对应的下载记录
      updateDownloadFromWS(message.data)
    }
  })
  wsUnsubscribers.push(unsubDownload)
  
  // 订阅上传更新
  const unsubUpload = wsClient.on('upload_update', (message) => {
    if (message.data) {
      updateUploadFromWS(message.data)
      // 不再频繁刷新整个列表，只更新单个记录，避免排序跳动
      // 如果记录不存在（可能是新创建的），才刷新列表
    }
  })
  wsUnsubscribers.push(unsubUpload)
  
  // 订阅清理更新（清理状态也会通过上传更新推送，但这里也处理以确保完整性）
  const unsubCleanup = wsClient.on('cleanup_update', (message) => {
    if (message.data && message.data.upload_id) {
      // 清理更新也通过上传更新来处理
      updateUploadFromWS({
        upload_id: message.data.upload_id,
        download_id: message.data.download_id,
        cleaned_at: message.data.cleaned_at
      })
      // 不再频繁刷新整个列表，避免排序跳动
    }
  })
  wsUnsubscribers.push(unsubCleanup)
  
  // 订阅统计更新（统计更新不需要刷新列表，避免排序跳动）
  const unsubStats = wsClient.on('statistics_update', (message) => {
    // 统计更新不影响列表排序，可以忽略或只更新统计信息
    // 如果需要更新统计，可以在dashboard页面处理
  })
  wsUnsubscribers.push(unsubStats)
  
  // 订阅初始数据
  const unsubInitial = wsClient.on('initial', (message) => {
    if (message.data) {
      // 收到初始数据，刷新列表
      fetchDownloads()
      fetchUploads()
    }
  })
  wsUnsubscribers.push(unsubInitial)
  
  // 订阅连接状态变化
  const unsubConnect = wsClient.on('pong', () => {
    // WebSocket 连接正常，确保轮询已停止
    checkConnectionAndPoll()
  })
  wsUnsubscribers.push(unsubConnect)
  
  // 初始检查连接状态
  setTimeout(() => {
    checkConnectionAndPoll()
  }, 1000)
})

// 从 WebSocket 更新下载记录
function updateDownloadFromWS(data: any) {
  const { gid, download_id, status, completed_length, total_length, download_speed } = data
  
  if (!gid && !download_id) {
    return // 没有有效的标识符，跳过更新
  }
  
  // 查找并更新对应的下载记录
  let found = false
  for (let groupIndex = 0; groupIndex < groups.value.length; groupIndex++) {
    const group = groups.value[groupIndex]
    if (!group.downloads) continue
    
    for (let downloadIndex = 0; downloadIndex < group.downloads.length; downloadIndex++) {
      const download = group.downloads[downloadIndex]
      
      // 严格匹配：优先使用 gid，如果没有 gid 则使用 download_id
      const matches = (gid && download.gid === gid) || (!gid && download_id && download.id === download_id)
      
      if (matches) {
        // 使用 Object.assign 确保 Vue 能检测到变化
        const updates: Partial<DownloadRecord> = {}
        if (status !== undefined) updates.status = status
        if (completed_length !== undefined) updates.completed_length = completed_length
        if (total_length !== undefined) updates.total_length = total_length
        if (download_speed !== undefined) updates.download_speed = download_speed
        // 不更新updated_at，避免触发不必要的响应式更新导致排序跳动
        
        // 更新记录
        Object.assign(download, updates)
        
        // 更新组的统计数据（因为下载状态改变可能影响组的统计）
        updateGroupStats(group)
        
        // 不再重新赋值整个数组，避免触发computed重新排序
        // Vue的响应式系统会自动检测Object.assign的变化
        
        found = true
        break
      }
    }
    if (found) break
  }
  
  // 如果记录不存在（可能是新创建的），刷新整个列表
  if (!found && (gid || download_id)) {
    fetchDownloads()
  }
}

// 从 WebSocket 更新上传记录
function updateUploadFromWS(data: any) {
  const { upload_id, download_id, status, uploaded_size, total_size, upload_speed, cleaned_at } = data
  
  if (!upload_id) {
    return // 没有有效的上传ID，跳过更新
  }
  
  let found = false
  
  // 更新上传列表中的记录
  const uploadIndex = uploads.value.findIndex(u => u.id === upload_id)
  if (uploadIndex !== -1) {
    const upload = uploads.value[uploadIndex]
    const updates: Partial<UploadRecord> = {}
    if (status !== undefined) updates.status = status
    if (uploaded_size !== undefined) updates.uploaded_size = uploaded_size
    if (total_size !== undefined) updates.total_size = total_size
    if (upload_speed !== undefined) updates.upload_speed = upload_speed
    if (cleaned_at !== undefined) updates.cleaned_at = cleaned_at  // 更新清理状态
    
    // 使用 Object.assign 确保 Vue 能检测到变化
    Object.assign(upload, updates)
    
    // 不再重新赋值整个数组，避免触发computed重新排序
    // Vue的响应式系统会自动检测Object.assign的变化
    
    found = true
  }
  
  // 同时更新下载记录中的上传信息
  for (let groupIndex = 0; groupIndex < groups.value.length; groupIndex++) {
    const group = groups.value[groupIndex]
    if (!group.downloads) continue
    
    for (let downloadIndex = 0; downloadIndex < group.downloads.length; downloadIndex++) {
      const download = group.downloads[downloadIndex]
      
      if (download.id === download_id && download.uploads) {
        for (let uploadIndex = 0; uploadIndex < download.uploads.length; uploadIndex++) {
          const upload = download.uploads[uploadIndex]
          
          if (upload.id === upload_id) {
            const updates: Partial<UploadRecord> = {}
            if (status !== undefined) updates.status = status
            if (uploaded_size !== undefined) updates.uploaded_size = uploaded_size
            if (total_size !== undefined) updates.total_size = total_size
            if (upload_speed !== undefined) updates.upload_speed = upload_speed
            if (cleaned_at !== undefined) updates.cleaned_at = cleaned_at  // 更新清理状态
            
            // 使用 Object.assign 确保 Vue 能检测到变化
            Object.assign(upload, updates)
            
            // 更新组的统计数据（因为上传状态改变可能影响组的完成状态）
            updateGroupStats(group)
            
            // 不再重新赋值整个数组，避免触发computed重新排序
            // Vue的响应式系统会自动检测Object.assign的变化
            
            found = true
            break
          }
        }
        if (found) break
      }
    }
    if (found) break
  }
  
  // 如果记录不存在（可能是新创建的），才刷新上传列表
  if (!found && upload_id) {
    fetchUploads()
  }
}

// 更新组的统计数据（基于下载和上传状态重新计算）
function updateGroupStats(group: DownloadGroup) {
  if (!group.downloads || group.downloads.length === 0) {
    return
  }
  
  let total_files = 0
  let completed = 0
  let downloading = 0
  let failed = 0
  let pending = 0
  let skipped = 0
  let total_size = 0
  let completed_size = 0
  
  for (const download of group.downloads) {
    total_files++
    
    const downloadStatus = download.status || 'pending'
    const uploads = download.uploads || []
    
    // 检查是否真正完成（下载完成且所有上传都完成或失败）
    const isTrulyCompleted = () => {
      if (downloadStatus !== 'completed') {
        return false
      }
      if (uploads.length === 0) {
        return true
      }
      for (const upload of uploads) {
        const uploadStatus = upload.status
        if (uploadStatus && ['uploading', 'pending', 'waiting_download'].includes(uploadStatus)) {
          return false
        }
      }
      return true
    }
    
    if (isTrulyCompleted()) {
      completed++
    } else if (downloadStatus === 'downloading') {
      downloading++
    } else if (downloadStatus === 'failed') {
      failed++
    } else if (downloadStatus === 'pending') {
      pending++
    } else if (downloadStatus === 'skipped' || (download.error_message && download.error_message.includes('跳过'))) {
      skipped++
    }
    
    // 计算大小
    const fileSize = download.total_length || download.file_size || 0
    total_size += fileSize
    
    if (downloadStatus === 'completed') {
      completed_size += fileSize
    }
  }
  
  // 更新组的统计数据
  group.stats = {
    total_files,
    completed,
    downloading,
    failed,
    pending,
    skipped,
    total_size,
    completed_size
  }
}

</script>

<style scoped>
.tasks-center-page {
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

.tasks-center-page :deep(.el-card) {
  border-radius: 16px;
  border: 1px solid rgba(229, 231, 235, 0.8);
  transition: all 0.3s ease;
  overflow: hidden;
}

.tasks-center-page :deep(.el-card:hover) {
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

.downloads-tabs :deep(.el-tabs__header) {
  margin: 0 0 12px 0;
}

.downloads-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background-color: rgba(229, 231, 235, 0.8);
}

.downloads-tabs :deep(.el-tabs__item) {
  font-weight: 600;
}

.downloads-tabs :deep(.el-tabs__item.is-active) {
  color: #667eea;
}

.downloads-tabs :deep(.el-tabs__active-bar) {
  background-color: #667eea;
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

/* 上传信息样式 */
.upload-info {
  @apply space-y-1;
}

.upload-item {
  @apply flex flex-col gap-1;
}

.upload-progress {
  @apply flex items-center gap-2;
}

.upload-speed {
  @apply text-xs text-gray-600;
  font-size: 11px;
}

.upload-error {
  @apply flex items-center;
}

/* 详情对话框样式 */
:deep(.file-detail-dialog) {
  animation: dialogFadeIn 0.3s ease-out;
}

:deep(.file-detail-dialog .el-dialog) {
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
  overflow: hidden;
}

:deep(.file-detail-dialog .el-dialog__header) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 20px 24px;
  margin: 0;
}

:deep(.file-detail-dialog .el-dialog__title) {
  color: white;
  font-weight: 600;
  font-size: 18px;
}

:deep(.file-detail-dialog .el-dialog__headerbtn) {
  top: 20px;
  right: 24px;
}

:deep(.file-detail-dialog .el-dialog__headerbtn .el-dialog__close) {
  color: white;
  font-size: 20px;
}

:deep(.file-detail-dialog .el-dialog__headerbtn:hover .el-dialog__close) {
  color: rgba(255, 255, 255, 0.8);
}

:deep(.file-detail-dialog .el-dialog__body) {
  padding: 24px;
  background: linear-gradient(to bottom, #fafbfc, #ffffff);
}

.file-detail-content {
  animation: contentSlideIn 0.4s ease-out;
}

.detail-descriptions :deep(.el-descriptions__label) {
  font-weight: 600;
  color: #374151;
  width: 140px;
}

.detail-descriptions :deep(.el-descriptions__content) {
  color: #6b7280;
}

.detail-descriptions :deep(.el-descriptions__table) {
  border-radius: 8px;
  overflow: hidden;
}

.detail-descriptions :deep(.el-descriptions__table td) {
  padding: 16px 20px;
  transition: background-color 0.2s ease;
}

.detail-descriptions :deep(.el-descriptions__table tr:hover td) {
  background-color: rgba(102, 126, 234, 0.05);
}

.detail-descriptions :deep(.el-descriptions__table .el-descriptions__label) {
  background-color: rgba(249, 250, 251, 0.8);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  padding: 16px 24px;
  background: rgba(249, 250, 251, 0.5);
  border-top: 1px solid rgba(229, 231, 235, 0.8);
}

/* 动画定义 */
@keyframes dialogFadeIn {
  from {
    opacity: 0;
    transform: scale(0.9);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes contentSlideIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 远程路径样式优化 */
.text-green-600 {
  color: #16a34a;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 13px;
  word-break: break-all;
  line-height: 1.6;
}

/* 表格行点击效果 */
.group-downloads :deep(.el-table__row) {
  cursor: pointer;
  transition: all 0.2s ease;
}

.group-downloads :deep(.el-table__row:hover) {
  background-color: rgba(102, 126, 234, 0.08);
  transform: translateX(4px);
}
</style>
