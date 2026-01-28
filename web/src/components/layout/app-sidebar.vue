<template>
  <el-aside :width="isCollapse ? '64px' : '240px'" class="sidebar">
    <div class="logo-container">
      <div v-if="!isCollapse" class="logo">
        <div class="logo-icon-wrapper">
          <el-icon :size="28" class="logo-icon"><Cpu /></el-icon>
        </div>
        <span class="logo-text">MistRelay</span>
      </div>
      <div v-else class="logo-icon-wrapper collapsed">
        <el-icon :size="28" class="logo-icon"><Cpu /></el-icon>
      </div>
    </div>
    
    <el-menu
      :default-active="activeRoute"
      :collapse="isCollapse"
      router
      class="sidebar-menu"
      background-color="transparent"
      text-color="#e5e7eb"
      active-text-color="#ffffff"
    >
      <el-menu-item index="/dashboard" class="menu-item">
        <el-icon><Odometer /></el-icon>
        <template #title>仪表板</template>
      </el-menu-item>
      
      <el-menu-item index="/downloads" class="menu-item">
        <el-icon><Download /></el-icon>
        <template #title>任务中心</template>
      </el-menu-item>
      
      <el-menu-item index="/tasks" class="menu-item">
        <el-icon><List /></el-icon>
        <template #title>任务队列</template>
      </el-menu-item>
      
      <el-menu-item index="/settings" class="menu-item">
        <el-icon><Setting /></el-icon>
        <template #title>系统设置</template>
      </el-menu-item>
      
      <el-menu-item index="/system" class="menu-item">
        <el-icon><Tools /></el-icon>
        <template #title>系统管理</template>
      </el-menu-item>
    </el-menu>
    
    <div class="sidebar-footer">
      <el-button
        :icon="isCollapse ? Expand : Fold"
        circle
        text
        @click="toggleCollapse"
        class="collapse-btn"
      />
    </div>
  </el-aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  Cpu,
  Odometer,
  Download,
  List,
  Setting,
  Tools,
  Expand,
  Fold
} from '@element-plus/icons-vue'

const route = useRoute()
const isCollapse = ref(false)

const activeRoute = computed(() => route.path)

const emit = defineEmits<{
  collapseChange: [collapsed: boolean]
}>()

function toggleCollapse() {
  isCollapse.value = !isCollapse.value
  emit('collapseChange', isCollapse.value)
}
</script>

<style scoped>
.sidebar {
  background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
  @apply h-screen fixed left-0 top-0 transition-all duration-300 ease-in-out z-50;
  box-shadow: 4px 0 24px rgba(0, 0, 0, 0.12);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
}

.logo-container {
  @apply h-16 flex items-center justify-center;
  @apply px-4;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.logo {
  @apply flex items-center gap-3 text-white font-bold text-xl;
  animation: slideInLeft 0.5s ease-out;
}

.logo-icon-wrapper {
  @apply w-10 h-10 rounded-xl flex items-center justify-center;
  background: var(--gradient-primary);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
  animation: glow 2s ease-in-out infinite;
}

.logo-icon-wrapper.collapsed {
  @apply w-12 h-12;
}

.logo-icon {
  @apply text-white;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.3));
}

.logo-text {
  @apply whitespace-nowrap;
  background: linear-gradient(135deg, #ffffff 0%, #e0e7ff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-shadow: 0 2px 8px rgba(255, 255, 255, 0.1);
}

.sidebar-menu {
  @apply border-none;
  height: calc(100vh - 128px);
  overflow-y: auto;
  padding: 12px 8px;
}

/* 自定义滚动条 */
.sidebar-menu::-webkit-scrollbar {
  width: 4px;
}

.sidebar-menu::-webkit-scrollbar-track {
  background: transparent;
}

.sidebar-menu::-webkit-scrollbar-thumb {
  @apply bg-gray-600 rounded-full;
}

.sidebar-menu:deep(.el-menu-item) {
  @apply rounded-lg my-1 mx-0;
  @apply transition-all duration-300;
  border: 1px solid transparent;
  position: relative;
  overflow: hidden;
}

.sidebar-menu:deep(.el-menu-item):before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  width: 3px;
  height: 100%;
  background: var(--gradient-primary);
  transform: scaleY(0);
  transition: transform 0.3s ease;
}

.sidebar-menu:deep(.el-menu-item):hover {
  @apply bg-gray-700/50;
  border-color: rgba(102, 126, 234, 0.3);
  transform: translateX(4px);
}

.sidebar-menu:deep(.el-menu-item):hover:before {
  transform: scaleY(1);
}

.sidebar-menu:deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(102, 126, 234, 0.2) 0%, rgba(118, 75, 162, 0.1) 100%);
  border-color: rgba(102, 126, 234, 0.4);
  @apply text-white;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.2);
}

.sidebar-menu:deep(.el-menu-item.is-active):before {
  transform: scaleY(1);
}

.sidebar-menu:deep(.el-menu-item .el-icon) {
  @apply transition-transform duration-300;
}

.sidebar-menu:deep(.el-menu-item:hover .el-icon) {
  transform: scale(1.1);
}

.sidebar-menu:deep(.el-menu-item.is-active .el-icon) {
  color: #667eea;
  filter: drop-shadow(0 0 8px rgba(102, 126, 234, 0.6));
}

/* 折叠状态样式 */
.sidebar-menu:deep(.el-menu--collapse .el-menu-item) {
  @apply flex items-center justify-center;
}

.sidebar-footer {
  @apply h-16 flex items-center justify-center;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.collapse-btn {
  @apply text-gray-400;
  @apply transition-all duration-300;
  @apply hover:text-white hover:bg-gray-700/50;
  @apply hover:scale-110;
}

.collapse-btn:hover {
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}
</style>
