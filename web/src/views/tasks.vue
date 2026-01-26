<template>
  <div class="tasks-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>队列状态</span>
          <el-button-group>
            <el-button @click="fetchQueue" :icon="Refresh" size="small">刷新</el-button>
            <el-button @click="autoRefresh = !autoRefresh" :type="autoRefresh ? 'primary' : ''" size="small">
              {{ autoRefresh ? '停止自动刷新' : '开启自动刷新' }}
            </el-button>
          </el-button-group>
        </div>
      </template>

      <!-- 限流警告 -->
      <el-alert
        v-if="queueData?.flood_wait?.is_waiting"
        type="warning"
        :closable="false"
        show-icon
        class="flood-wait-alert"
      >
        <template #title>
          <strong>⚠️ Telegram 限流中</strong>
        </template>
        <div class="flood-wait-info">
          <p><strong>限流时长:</strong> {{ queueData.flood_wait.wait_seconds }} 秒 ({{ Math.floor(queueData.flood_wait.wait_seconds / 60) }} 分钟)</p>
          <p><strong>剩余时间:</strong> {{ queueData.flood_wait.remaining_seconds }} 秒</p>
          <p class="flood-wait-message">所有消息已进入等待队列,限流结束后将自动恢复处理</p>
        </div>
      </el-alert>

      <!-- 队列统计 -->
      <div class="queue-stats">
        <el-statistic title="队列大小" :value="queueSize">
          <template #suffix>
            <span class="stat-suffix">个任务</span>
          </template>
        </el-statistic>
        <el-statistic title="等待中" :value="waitingItems.length">
          <template #suffix>
            <span class="stat-suffix">个</span>
          </template>
        </el-statistic>
      </div>

      <el-divider />

      <!-- 当前处理 -->
      <div class="current-processing">
        <h3>正在处理</h3>
        <el-empty v-if="!currentProcessing" description="当前没有正在处理的任务" :image-size="80" />
        <el-card v-else shadow="never" class="processing-card">
          <div class="processing-info">
            <el-tag type="primary" size="large">处理中</el-tag>
            <div class="processing-details">
              <p><strong>标题:</strong> {{ currentProcessing.title }}</p>
              <p><strong>类型:</strong> {{ currentProcessing.type === 'media_group' ? '媒体组' : '单个文件' }}</p>
              <p v-if="currentProcessing.media_group_total"><strong>文件数:</strong> {{ currentProcessing.media_group_total }}</p>
              <p v-if="currentProcessing.task_gids && currentProcessing.task_gids.length">
                <strong>下载任务:</strong> {{ currentProcessing.task_gids.length }} 个
              </p>
            </div>
          </div>
        </el-card>
      </div>

      <el-divider />

      <!-- 等待队列 -->
      <div class="waiting-queue">
        <h3>等待队列 ({{ waitingItems.length }})</h3>
        <el-empty v-if="waitingItems.length === 0" description="队列为空" :image-size="80" />
        <el-timeline v-else>
          <el-timeline-item
            v-for="(item, index) in waitingItems"
            :key="item.queue_id"
            :timestamp="`位置 ${index + 1}`"
            placement="top"
          >
            <el-card shadow="never" class="queue-item-card">
              <div class="queue-item-info">
                <el-tag :type="item.type === 'media_group' ? 'warning' : 'info'" size="small">
                  {{ item.type === 'media_group' ? '媒体组' : '单个文件' }}
                </el-tag>
                <p class="item-title">{{ item.title }}</p>
                <p v-if="item.media_group_total" class="item-detail">
                  包含 {{ item.media_group_total }} 个文件
                </p>
              </div>
            </el-card>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { useIntervalFn } from '@vueuse/core'
import { getQueue } from '@/api'
import TaskList from '@/components/tasks/task-list.vue'

const activeTab = ref('processing')
const autoRefresh = ref(true)
const queueData = ref<any>(null)

const currentProcessing = computed(() => queueData.value?.current_processing || null)
const waitingItems = computed(() => queueData.value?.waiting_items || [])
const queueSize = computed(() => queueData.value?.queue_size || 0)

function fetchQueue() {
  getQueue()
    .then(data => {
      if (data.success) {
        queueData.value = data
      }
    })
    .catch(err => console.error('获取队列状态失败:', err))
}

function handleTabChange() {
  // 切换标签页时可以执行额外操作
}

watch(autoRefresh, (enabled) => {
  if (enabled) {
    useIntervalFn(fetchQueue, 3000) // 队列状态每3秒刷新一次
  }
})

onMounted(() => {
  fetchQueue()
  if (autoRefresh.value) {
    useIntervalFn(fetchQueue, 3000)
  }
})
</script>

<style scoped>
.tasks-page {
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

.tasks-page :deep(.el-card) {
  border-radius: 16px;
  border: 1px solid rgba(229, 231, 235, 0.8);
  transition: all 0.3s ease;
  overflow: hidden;
}

.tasks-page :deep(.el-card:hover) {
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.08);
  border-color: rgba(102, 126, 234, 0.2);
}

.tasks-page :deep(.el-card__header) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(249, 250, 251, 0.9));
  border-bottom: 1px solid rgba(229, 231, 235, 0.8);
  padding: 20px 24px;
}

.card-header {
  @apply flex items-center justify-between;
}

.card-header span {
  @apply text-lg font-semibold text-gray-800;
}

/* 队列统计 */
.queue-stats {
  @apply flex gap-8 mb-6;
}

.stat-suffix {
  @apply text-sm text-gray-500 ml-1;
}

/* 限流警告 */
.flood-wait-alert {
  @apply mb-6;
  border-radius: 12px;
  border: 2px solid #f59e0b;
}

.flood-wait-info {
  @apply mt-2 space-y-2;
}

.flood-wait-info p {
  @apply mb-1;
}

.flood-wait-message {
  @apply text-sm text-gray-600 mt-3;
  font-style: italic;
}

/* 当前处理 */
.current-processing h3,
.waiting-queue h3 {
  @apply text-lg font-semibold text-gray-800 mb-4;
}

.processing-card {
  @apply bg-blue-50 border-blue-200;
}

.processing-info {
  @apply flex items-start gap-4;
}

.processing-details {
  @apply flex-1;
}

.processing-details p {
  @apply mb-2 text-gray-700;
}

/* 等待队列 */
.queue-item-card {
  @apply bg-gray-50;
}

.queue-item-info {
  @apply space-y-2;
}

.item-title {
  @apply font-semibold text-gray-800;
}

.item-detail {
  @apply text-sm text-gray-600;
}

/* 时间线美化 */
:deep(.el-timeline-item__timestamp) {
  @apply font-semibold text-blue-600;
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
  border-radius: 8px;
}

/* 统计数字美化 */
:deep(.el-statistic__head) {
  @apply text-gray-600 font-medium;
}

:deep(.el-statistic__content) {
  @apply text-2xl font-bold text-gray-900;
}
</style>
