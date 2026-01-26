<template>
  <div class="task-list">
    <el-table :data="tasks" stripe style="width: 100%" v-loading="loading">
      <el-table-column prop="file_name" label="文件名" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.file_name || row.source_url?.substring(0, 50) || '未知文件' }}
        </template>
      </el-table-column>
      
      <el-table-column label="大小" width="120">
        <template #default="{ row }">
          {{ formatSize(row.total_length || row.file_size) }}
        </template>
      </el-table-column>
      
      <el-table-column label="进度" width="200" v-if="status === 'downloading'">
        <template #default="{ row }">
          <el-progress
            :percentage="getProgress(row.total_length, row.completed_length, row.status)"
            :status="getProgressStatus(row.status)"
            :stroke-width="8"
          />
        </template>
      </el-table-column>
      
      <el-table-column label="速度" width="100" v-if="status === 'downloading'">
        <template #default="{ row }">
          {{ formatSpeed(row.download_speed) }}
        </template>
      </el-table-column>
      
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="getStatusTagType(row.status)" size="small">
            {{ getStatusText(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button-group>
            <el-button
              v-if="status === 'downloading'"
              size="small"
              :icon="VideoPause"
              @click="handlePause(row)"
              title="暂停"
            />
            <el-button
              v-if="status === 'pending'"
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
    
    <div v-if="tasks.length === 0" class="empty-state">
      <el-empty description="暂无任务" :image-size="100" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { VideoPause, VideoPlay, Delete } from '@element-plus/icons-vue'
import type { DownloadRecord } from '@/types/api'
import {
  formatSize,
  formatDate,
  getProgress,
  getStatusText,
  getStatusTagType
} from '@/utils/formatters'

interface Props {
  tasks: DownloadRecord[]
  status?: string
}

const props = defineProps<Props>()
const emit = defineEmits<{
  refresh: []
}>()

const loading = ref(false)

function formatSpeed(speed?: number): string {
  if (!speed) return '-'
  return formatSize(speed) + '/s'
}

function getProgressStatus(status?: string): 'success' | 'exception' | 'warning' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  return 'warning'
}

function handlePause(task: DownloadRecord) {
  ElMessage.info('暂停功能需要后端API支持')
  // TODO: 调用API暂停任务
}

function handleResume(task: DownloadRecord) {
  ElMessage.info('恢复功能需要后端API支持')
  // TODO: 调用API恢复任务
}

function handleDelete(task: DownloadRecord) {
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
    // TODO: 调用API删除任务
    emit('refresh')
  }).catch(() => {})
}
</script>

<style scoped>
.task-list {
  @apply min-h-[400px];
}

.empty-state {
  @apply py-12;
}
</style>
