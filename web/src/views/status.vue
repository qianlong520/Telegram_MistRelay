<template>
  <div class="status-page">
      <el-skeleton v-if="isLoading" :rows="5" animated />
      
      <el-alert
        v-else-if="error"
        :title="`加载失败: ${error}`"
        type="error"
        :closable="false"
        class="mb-6"
      >
        <template #default>
          <el-button @click="fetchStatus" type="primary" class="mt-2">重试</el-button>
        </template>
      </el-alert>
      
      <div v-else-if="status" class="space-y-6">
        <el-card shadow="hover">
          <template #header>
            <h2 class="text-xl font-semibold">服务器信息</h2>
          </template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="运行状态">
              <el-tag type="success">{{ status.server_status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="运行时长">
              {{ status.uptime }}
            </el-descriptions-item>
            <el-descriptions-item label="版本">
              {{ status.version }}
            </el-descriptions-item>
            <el-descriptions-item label="Telegram Bot">
              {{ status.telegram_bot }}
            </el-descriptions-item>
            <el-descriptions-item label="已连接机器人">
              {{ status.connected_bots }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
        
        <el-card v-if="status.loads && Object.keys(status.loads).length > 0" shadow="hover">
          <template #header>
            <h2 class="text-xl font-semibold">负载状态</h2>
          </template>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div
              v-for="(load, bot) in status.loads"
              :key="bot"
              class="p-4 bg-gray-50 rounded-lg"
            >
              <div class="flex justify-between items-center">
                <span class="font-semibold text-gray-700">{{ bot }}:</span>
                <el-tag :type="getLoadTagType(load)" size="large">
                  {{ load }}
                </el-tag>
              </div>
            </div>
          </div>
        </el-card>
        
        <div class="text-center">
          <el-button @click="fetchStatus" type="primary" :icon="Refresh">
            刷新
          </el-button>
        </div>
      </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { useIntervalFn } from '@vueuse/core'
import { getStatus } from '@/api'
import type { ServerStatus } from '@/types/api'

const status = ref<ServerStatus | null>(null)
const isLoading = ref(true)
const error = ref<string | null>(null)

function fetchStatus() {
  isLoading.value = true
  error.value = null
  getStatus()
    .then(data => {
      status.value = data
    })
    .catch(err => {
      error.value = err.message || '未知错误'
      console.error('获取状态失败:', err)
    })
    .finally(() => {
      isLoading.value = false
    })
}

function getLoadTagType(load: number): 'success' | 'warning' | 'danger' {
  if (load === 0) return 'success'
  if (load <= 2) return 'success'
  if (load <= 5) return 'warning'
  return 'danger'
}

onMounted(() => {
  fetchStatus()
  // 每30秒自动刷新
  useIntervalFn(fetchStatus, 30000)
})
</script>

<style scoped>
.status-page {
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
</style>
