<template>
  <div class="system-page">
    <el-row :gutter="20">
      <!-- Docker容器状态 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="mb-6">
          <template #header>
            <div class="flex justify-between items-center">
              <span>Docker容器状态</span>
              <el-button 
                :icon="Refresh" 
                circle 
                size="small" 
                @click="fetchDockerStatus"
                :loading="loadingStatus"
              />
            </div>
          </template>
          
          <el-skeleton v-if="loadingStatus" :rows="5" animated />
          
          <div v-else-if="dockerStatus">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="运行环境">
                <el-tag :type="dockerStatus.in_docker ? 'success' : 'info'" size="small">
                  {{ dockerStatus.in_docker ? 'Docker容器内' : '非Docker环境' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="容器名称">
                {{ dockerStatus.container_name || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="运行状态">
                <el-tag 
                  :type="getStatusType(dockerStatus.status)" 
                  size="small"
                >
                  {{ dockerStatus.status || '-' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="镜像名称">
                {{ dockerStatus.image || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="创建时间">
                {{ formatDate(dockerStatus.created) }}
              </el-descriptions-item>
            </el-descriptions>
            
            <div v-if="dockerStatus.error" class="mt-4">
              <el-alert
                :title="dockerStatus.error"
                type="warning"
                :closable="false"
              />
            </div>
          </div>
          
          <el-empty v-else description="无法获取容器状态" />
        </el-card>
      </el-col>

      <!-- Docker控制操作 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="mb-6">
          <template #header>
            <span>容器控制</span>
          </template>
          
          <div class="control-actions">
            <el-button 
              type="primary" 
              :icon="RefreshRight" 
              @click="handleRestart"
              :loading="restarting"
              :disabled="!dockerStatus?.in_docker"
              block
              size="large"
            >
              重启容器（热重载）
            </el-button>
            
            <el-alert
              v-if="!dockerStatus?.in_docker"
              title="当前不在Docker容器内运行，无法执行容器操作"
              type="info"
              :closable="false"
              class="mt-4"
            />
            
            <div v-if="restartMessage" class="mt-4">
              <el-alert
                :title="restartMessage"
                :type="restartSuccess ? 'success' : 'error'"
                :closable="true"
                @close="restartMessage = ''"
              />
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Docker日志 -->
    <el-card shadow="hover">
      <template #header>
        <div class="flex justify-between items-center">
          <span>容器日志</span>
          <div class="flex gap-2">
            <el-select 
              v-model="logLines" 
              @change="handleLogLinesChange"
              style="width: 120px"
              size="small"
              :disabled="wsConnected"
            >
              <el-option label="50 行" :value="50" />
              <el-option label="100 行" :value="100" />
              <el-option label="200 行" :value="200" />
              <el-option label="500 行" :value="500" />
            </el-select>
            <el-button 
              v-if="!wsConnected"
              :icon="VideoPlay"
              circle 
              size="small" 
              @click="startLogStream"
              :loading="connecting"
              title="开始实时日志"
            />
            <el-button 
              v-else
              :icon="VideoPause"
              circle 
              size="small" 
              @click="stopLogStream"
              title="停止实时日志"
            />
            <el-button 
              :icon="Refresh" 
              circle 
              size="small" 
              @click="fetchLogs"
              :loading="loadingLogs"
              :disabled="wsConnected"
              title="刷新日志"
            />
            <el-button 
              :icon="Delete"
              circle 
              size="small" 
              @click="clearLogs"
              title="清空日志"
            />
          </div>
        </div>
      </template>
      
      <el-skeleton v-if="loadingLogs && !wsConnected" :rows="10" animated />
      
      <div v-else class="logs-container" ref="logsContainerRef">
        <pre class="logs-content" ref="logsContentRef">{{ dockerLogs }}</pre>
      </div>
      
      <el-empty v-if="!dockerLogs && !wsConnected" description="无法获取容器日志" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, RefreshRight, VideoPlay, VideoPause, Delete } from '@element-plus/icons-vue'
import { getDockerStatus, restartDocker, getDockerLogs } from '@/api'
import type { DockerStatus } from '@/types/api'
import { formatDate } from '@/utils/formatters'

const dockerStatus = ref<DockerStatus | null>(null)
const dockerLogs = ref<string>('')
const loadingStatus = ref(false)
const loadingLogs = ref(false)
const restarting = ref(false)
const restartMessage = ref('')
const restartSuccess = ref(false)
const logLines = ref(100)
const wsConnected = ref(false)
const connecting = ref(false)
const ws = ref<WebSocket | null>(null)
const logsContainerRef = ref<HTMLElement | null>(null)
const logsContentRef = ref<HTMLElement | null>(null)

function fetchDockerStatus() {
  loadingStatus.value = true
  getDockerStatus()
    .then(data => {
      dockerStatus.value = data
    })
    .catch(err => {
      console.error('获取Docker状态失败:', err)
      ElMessage.error('获取Docker状态失败')
    })
    .finally(() => {
      loadingStatus.value = false
    })
}

function fetchLogs() {
  loadingLogs.value = true
  getDockerLogs(logLines.value)
    .then(data => {
      if (data.success && data.logs) {
        dockerLogs.value = data.logs
      } else {
        dockerLogs.value = ''
        ElMessage.warning(data.error || '无法获取日志')
      }
    })
    .catch(err => {
      console.error('获取Docker日志失败:', err)
      ElMessage.error('获取Docker日志失败')
      dockerLogs.value = ''
    })
    .finally(() => {
      loadingLogs.value = false
    })
}

function handleRestart() {
  if (!dockerStatus.value?.in_docker) {
    ElMessage.warning('当前不在Docker容器内运行')
    return
  }

  ElMessageBox.confirm(
    '确定要重启Docker容器吗？重启后服务会短暂中断。',
    '确认重启',
    {
      confirmButtonText: '确定重启',
      cancelButtonText: '取消',
      type: 'warning',
      dangerouslyUseHTMLString: false
    }
  ).then(() => {
    restarting.value = true
    restartMessage.value = ''
    
    restartDocker()
      .then(data => {
        if (data.success) {
          restartSuccess.value = true
          restartMessage.value = data.message || '容器重启成功'
          ElMessage.success(restartMessage.value)
          // 延迟刷新状态
          setTimeout(() => {
            fetchDockerStatus()
            fetchLogs()
          }, 2000)
        } else {
          restartSuccess.value = false
          restartMessage.value = data.error || '重启失败'
          ElMessage.error(restartMessage.value)
        }
      })
      .catch(err => {
        restartSuccess.value = false
        restartMessage.value = err.message || '重启操作失败'
        ElMessage.error(restartMessage.value)
        console.error('重启Docker容器失败:', err)
      })
      .finally(() => {
        restarting.value = false
      })
  }).catch(() => {
    // 用户取消
  })
}

function getStatusType(status?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (!status) return 'info'
  const lowerStatus = status.toLowerCase()
  if (lowerStatus.includes('running') || lowerStatus.includes('up')) {
    return 'success'
  }
  if (lowerStatus.includes('restarting') || lowerStatus.includes('paused')) {
    return 'warning'
  }
  if (lowerStatus.includes('stopped') || lowerStatus.includes('exited')) {
    return 'danger'
  }
  return 'info'
}

onMounted(() => {
  fetchDockerStatus()
  fetchLogs()
})

onUnmounted(() => {
  // 组件卸载时关闭WebSocket连接
  stopLogStream()
})
</script>

<style scoped>
.system-page {
  @apply space-y-6;
}

.page-header {
  @apply mb-6;
}

.page-title {
  @apply text-3xl font-bold text-gray-800 mb-2;
}

.page-subtitle {
  @apply text-gray-600;
}

.control-actions {
  @apply space-y-4;
}

.logs-container {
  @apply bg-gray-900 rounded-lg p-4 overflow-auto;
  max-height: 600px;
  font-family: 'Courier New', monospace;
  position: relative;
}

.logs-content {
  @apply text-gray-100 text-sm whitespace-pre-wrap;
  margin: 0;
  line-height: 1.5;
  word-break: break-all;
}

.logs-container::-webkit-scrollbar {
  width: 8px;
}

.logs-container::-webkit-scrollbar-track {
  @apply bg-gray-800 rounded;
}

.logs-container::-webkit-scrollbar-thumb {
  @apply bg-gray-600 rounded;
}

.logs-container::-webkit-scrollbar-thumb:hover {
  @apply bg-gray-500;
}

:deep(.el-descriptions__label) {
  @apply font-medium;
}
</style>
