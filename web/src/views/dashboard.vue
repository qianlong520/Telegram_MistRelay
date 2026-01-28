<template>
  <div class="dashboard">
    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stats-row">
      <el-col :xs="24" :sm="12" :md="6" v-for="stat in stats" :key="stat.key">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <div class="stat-icon" :style="{ background: stat.color }">
              <el-icon :size="24"><component :is="stat.icon" /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stat.value }}</div>
              <div class="stat-label">{{ stat.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表区域 -->
    <el-row :gutter="20" class="charts-row">
      <el-col :xs="24" :lg="16">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span>实时监控</span>
          </template>
          <div class="chart-container" ref="chartRef"></div>
        </el-card>
      </el-col>
      
      <el-col :xs="24" :lg="8">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span>系统负载</span>
          </template>
          <div v-if="status" class="load-status">
            <div v-for="(load, bot) in status.loads" :key="bot" class="load-item">
              <div class="load-header">
                <span class="load-bot">{{ bot }}</span>
                <el-tag :type="getLoadTagType(load)" size="small">{{ load }}</el-tag>
              </div>
              <el-progress
                :percentage="getLoadPercentage(load)"
                :color="getLoadColor(load)"
                :stroke-width="8"
              />
            </div>
          </div>
          <el-skeleton v-else :rows="4" animated />
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近活动 -->
    <el-row :gutter="20" class="activity-row">
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>最近下载</span>
              <el-button size="small" @click="$router.push('/downloads')">查看全部</el-button>
            </div>
          </template>
          <el-table :data="recentDownloads" style="width: 100%" size="small">
            <el-table-column prop="file_name" label="文件名" show-overflow-tooltip />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="getStatusTagType(row.status)" size="small">
                  {{ getStatusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="160">
              <template #default="{ row }">
                {{ formatDate(row.created_at) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover">
          <template #header>
            <span>系统信息</span>
          </template>
          <el-descriptions v-if="status" :column="1" border size="small">
            <el-descriptions-item label="运行状态">
              <el-tag type="success" size="small">{{ status.server_status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="运行时长">{{ status.uptime }}</el-descriptions-item>
            <el-descriptions-item label="Telegram Bot">{{ status.telegram_bot }}</el-descriptions-item>
            <el-descriptions-item label="已连接机器人">{{ status.connected_bots }}</el-descriptions-item>
            <el-descriptions-item label="版本">{{ status.version }}</el-descriptions-item>
          </el-descriptions>
          <el-skeleton v-else :rows="5" animated />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useIntervalFn, useResizeObserver } from '@vueuse/core'
import * as echarts from 'echarts'
import {
  Check,
  Warning,
  Delete,
  Document
} from '@element-plus/icons-vue'
import { getStatus, getDownloads, getSystemTrend, getDownloadStatistics, getUploadStatistics, type TrendPoint } from '@/api'
import type { ServerStatus, DownloadRecord } from '@/types/api'
import { formatDate, getStatusText, getStatusTagType } from '@/utils/formatters'

const status = ref<ServerStatus | null>(null)
const recentDownloads = ref<DownloadRecord[]>([])
const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

const stats = ref([
  {
    key: 'completed',
    label: '完成',
    value: 0,
    icon: Check,
    color: 'linear-gradient(135deg, #10b981 0%, #059669 100%)'
  },
  {
    key: 'cleaned',
    label: '清理',
    value: 0,
    icon: Delete,
    color: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)'
  },
  {
    key: 'failed',
    label: '失败',
    value: 0,
    icon: Warning,
    color: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)'
  },
  {
    key: 'total',
    label: '总计',
    value: 0,
    icon: Document,
    color: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
  }
])

function initChart() {
  if (!chartRef.value) return
  
  chartInstance = echarts.init(chartRef.value)
  
  const option = {
    tooltip: {
      trigger: 'axis',
      formatter: function (params: any) {
        let result = params[0].axisValueLabel + '<br/>'
        params.forEach((param: any) => {
          let value = param.value
          
          if (value > 1024 * 1024) {
            value = (value / (1024 * 1024)).toFixed(2) + ' MB/s'
          } else if (value > 1024) {
            value = (value / 1024).toFixed(2) + ' KB/s'
          } else {
            value = value + ' B/s'
          }
          
          result += param.marker + param.seriesName + ': ' + value + '<br/>'
        })
        return result
      }
    },
    legend: {
      data: ['上传速度', '下载速度', 'IO占用'],
      bottom: 0
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '10%',
      top: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: [],
      axisLabel: {
        formatter: (value: string) => {
          // 时间戳是UTC时间戳（毫秒），需要转换为中国时区（UTC+8）
          const timestamp = parseInt(value)
          const date = new Date(timestamp)
          
          // 获取UTC时间的小时、分钟、秒
          const utcHours = date.getUTCHours()
          const utcMinutes = date.getUTCMinutes()
          const utcSeconds = date.getUTCSeconds()
          
          // 转换为中国时区（UTC+8）
          const cnHours = (utcHours + 8) % 24
          
          // 格式化时间
          return cnHours.toString().padStart(2, '0') + ':' + 
                 utcMinutes.toString().padStart(2, '0') + ':' + 
                 utcSeconds.toString().padStart(2, '0')
        }
      }
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        formatter: (value: number) => {
          if (value > 1024 * 1024) {
            return (value / (1024 * 1024)).toFixed(1) + ' M'
          } else if (value > 1024) {
            return (value / 1024).toFixed(1) + ' K'
          }
          return value
        }
      }
    },
    series: [
      {
        name: '上传速度',
        type: 'line',
        smooth: true,
        showSymbol: false,
        areaStyle: { opacity: 0.1 },
        data: []
      },
      {
        name: '下载速度',
        type: 'line',
        smooth: true,
        showSymbol: false,
        areaStyle: { opacity: 0.1 },
        data: []
      },
      {
        name: 'IO占用',
        type: 'line',
        smooth: true,
        showSymbol: false,
        areaStyle: { opacity: 0.1 },
        data: []
      }
    ],
    color: ['#667eea', '#10b981', '#f59e0b']
  }
  
  chartInstance.setOption(option)
}

function updateChart(data: TrendPoint[]) {
  if (!chartInstance) return
  
  const timestamps = data.map(p => p.timestamp)
  const uploads = data.map(p => p.upload)
  const downloads = data.map(p => p.download)
  const ios = data.map(p => p.io)
  
  chartInstance.setOption({
    xAxis: {
      data: timestamps
    },
    series: [
      { data: uploads },
      { data: downloads },
      { data: ios }
    ]
  })
}

function fetchTrend() {
  getSystemTrend()
    .then(response => {
      if (response.success && response.data) {
        updateChart(response.data)
      }
    })
    .catch(console.error)
}

function fetchData() {
  // 获取状态
  getStatus()
    .then(data => {
      status.value = data
    })
    .catch(err => console.error('获取状态失败:', err))

  // 获取下载统计和上传统计
  Promise.all([
    getDownloadStatistics(),
    getUploadStatistics()
  ])
    .then(([downloadResponse, uploadResponse]) => {
      const downloadData = downloadResponse.success ? downloadResponse.data : null
      const uploadData = uploadResponse.success ? uploadResponse.data : null
      
      if (downloadData || uploadData) {
        // 总数应该是下载任务总数（因为上传任务关联下载任务，避免重复计算）
        const totalTasks = downloadData?.total || 0
        updateStats({
          completed: downloadData?.completed || 0,
          cleaned: uploadData?.cleaned || 0,
          failed: downloadData?.failed || 0,
          total: totalTasks
        })
      }
    })
    .catch(err => console.error('获取统计失败:', err))

  // 获取最近下载（仅用于显示最近活动）
  getDownloads(10)
    .then(response => {
      if (response.success) {
        // 处理分组数据
        if (response.grouped && Array.isArray(response.data)) {
          // 展平分组数据
          const allDownloads: DownloadRecord[] = []
          response.data.forEach((group: any) => {
            if (group.downloads && Array.isArray(group.downloads)) {
              allDownloads.push(...group.downloads)
            }
          })
          recentDownloads.value = allDownloads.slice(0, 10)
        } else {
          // 非分组数据
          recentDownloads.value = (response.data as DownloadRecord[]) || []
        }
      }
    })
    .catch(err => console.error('获取下载记录失败:', err))
    
  fetchTrend()
}

function updateStats(statistics: { completed: number; cleaned: number; failed: number; total: number }) {
  stats.value.forEach(stat => {
    switch (stat.key) {
      case 'completed':
        stat.value = statistics.completed || 0
        break
      case 'cleaned':
        stat.value = statistics.cleaned || 0
        break
      case 'failed':
        stat.value = statistics.failed || 0
        break
      case 'total':
        stat.value = statistics.total || 0
        break
      default:
        stat.value = 0
    }
  })
}

function getLoadTagType(load: number): 'success' | 'warning' | 'danger' {
  if (load === 0) return 'success'
  if (load <= 2) return 'success'
  if (load <= 5) return 'warning'
  return 'danger'
}

function getLoadPercentage(load: number): number {
  return Math.min((load / 10) * 100, 100)
}

function getLoadColor(load: number): string {
  if (load === 0) return '#10b981'
  if (load <= 2) return '#10b981'
  if (load <= 5) return '#f59e0b'
  return '#ef4444'
}

onMounted(() => {
  fetchData()
  nextTick(() => {
    initChart()
    fetchTrend()
  })
  
  // 每2秒更新图表
  const { pause: pauseTrend } = useIntervalFn(fetchTrend, 2000)
  // 每30秒更新其他数据
  const { pause: pauseData } = useIntervalFn(fetchData, 30000)
  
  useResizeObserver(document.body, () => {
    chartInstance?.resize()
  })
  
  onUnmounted(() => {
    pauseTrend()
    pauseData()
    chartInstance?.dispose()
  })
})
</script>

<style scoped>
.dashboard {
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

.stats-row {
  @apply mb-8;
}

.stat-card {
  @apply cursor-pointer;
  @apply transition-all duration-300;
  border-radius: 16px;
  overflow: hidden;
  position: relative;
  background: white;
  border: 1px solid rgba(229, 231, 235, 0.8);
}

.stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.05), rgba(118, 75, 162, 0.05));
  opacity: 0;
  transition: opacity 0.3s ease;
}

.stat-card:hover {
  transform: translateY(-8px);
  box-shadow: 0 12px 24px rgba(102, 126, 234, 0.15);
  border-color: rgba(102, 126, 234, 0.3);
}

.stat-card:hover::before {
  opacity: 1;
}

.stat-card :deep(.el-card__body) {
  padding: 24px;
}

.stat-content {
  @apply flex items-center gap-5;
  position: relative;
  z-index: 1;
}

.stat-icon {
  @apply w-14 h-14 rounded-xl flex items-center justify-center text-white;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transition: all 0.3s ease;
}

.stat-card:hover .stat-icon {
  transform: scale(1.1) rotate(5deg);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
}

.stat-info {
  @apply flex-1;
}

.stat-value {
  @apply text-3xl font-bold text-gray-900 mb-1;
  font-variant-numeric: tabular-nums;
  transition: all 0.3s ease;
}

.stat-card:hover .stat-value {
  color: #667eea;
  transform: scale(1.05);
}

.stat-label {
  @apply text-sm text-gray-600 font-medium;
}

.charts-row {
  @apply mb-8;
}

.chart-card {
  @apply h-80;
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid rgba(229, 231, 235, 0.8);
  transition: all 0.3s ease;
}

.chart-card:hover {
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.08);
  border-color: rgba(102, 126, 234, 0.2);
}

.chart-card :deep(.el-card__header) {
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

.chart-container {
  @apply h-full w-full;
  min-height: 250px;
}

.load-status {
  @apply space-y-5;
  padding: 4px 0;
}

.load-item {
  @apply space-y-3;
  padding: 16px;
  border-radius: 12px;
  background: rgba(249, 250, 251, 0.5);
  transition: all 0.3s ease;
}

.load-item:hover {
  background: rgba(102, 126, 234, 0.05);
  transform: translateX(4px);
}

.load-header {
  @apply flex items-center justify-between;
}

.load-bot {
  @apply font-semibold text-gray-800;
  font-size: 15px;
}

.activity-row {
  @apply mt-8;
}

.activity-row :deep(.el-card) {
  border-radius: 16px;
  border: 1px solid rgba(229, 231, 235, 0.8);
  transition: all 0.3s ease;
}

.activity-row :deep(.el-card:hover) {
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.08);
  border-color: rgba(102, 126, 234, 0.2);
}

.activity-row :deep(.el-card__header) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(249, 250, 251, 0.9));
  border-bottom: 1px solid rgba(229, 231, 235, 0.8);
  padding: 20px 24px;
}

.activity-row :deep(.el-card__header span) {
  @apply text-lg font-semibold text-gray-800;
}

.activity-row :deep(.el-table) {
  border-radius: 8px;
}

.activity-row :deep(.el-table__row) {
  transition: all 0.2s ease;
}

.activity-row :deep(.el-table__row:hover) {
  background: linear-gradient(90deg, rgba(102, 126, 234, 0.05), rgba(118, 75, 162, 0.03));
}

.activity-row :deep(.el-descriptions) {
  border-radius: 8px;
}

.activity-row :deep(.el-descriptions__label) {
  @apply font-semibold;
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

/* 标签美化 */
:deep(.el-tag) {
  border-radius: 6px;
  font-weight: 500;
  border: none;
}

/* 按钮组美化 */
:deep(.el-button-group .el-button) {
  border-radius: 8px;
  transition: all 0.2s ease;
}

:deep(.el-button-group .el-button:hover) {
  transform: translateY(-1px);
}
</style>
