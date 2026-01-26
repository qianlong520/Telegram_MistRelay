<template>
  <el-header class="header">
    <div class="header-content">
      <!-- 左侧:面包屑导航 -->
      <div class="header-left">
        <el-breadcrumb separator="/" class="breadcrumb">
          <el-breadcrumb-item :to="{ path: '/dashboard' }" class="breadcrumb-item">
            <el-icon class="breadcrumb-icon"><HomeFilled /></el-icon>
            <span>首页</span>
          </el-breadcrumb-item>
          <el-breadcrumb-item v-if="breadcrumb && route.path !== '/dashboard'">
            {{ breadcrumb }}
          </el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      
      <!-- 右侧:用户信息 -->
      <div class="header-right">
        <el-dropdown trigger="click" @command="handleCommand" placement="bottom-end" class="user-dropdown">
          <div class="user-info">
            <el-avatar :size="40" class="avatar">
              <el-icon><User /></el-icon>
            </el-avatar>
            <div class="user-details">
              <span class="username">管理员</span>
              <span class="user-role">系统管理员</span>
            </div>
            <el-icon class="dropdown-icon"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu class="user-menu">
              <el-dropdown-item command="profile" class="menu-item">
                <el-icon><User /></el-icon>
                <span>个人设置</span>
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided class="menu-item logout-item">
                <el-icon><SwitchButton /></el-icon>
                <span>退出登录</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
  </el-header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { User, ArrowDown, SwitchButton, HomeFilled } from '@element-plus/icons-vue'

const route = useRoute()

const breadcrumb = computed(() => {
  const routeMap: Record<string, string> = {
    '/downloads': '下载管理',
    '/tasks': '任务队列',
    '/status': '系统状态',
    '/settings': '系统设置',
    '/system': '系统管理'
  }
  return routeMap[route.path]
})

function handleCommand(command: string) {
  if (command === 'logout') {
    // TODO: 实现退出登录逻辑
    console.log('退出登录')
  } else if (command === 'profile') {
    // TODO: 实现个人设置逻辑
    console.log('个人设置')
  }
}
</script>

<style scoped>
.header {
  @apply bg-white/80;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(229, 231, 235, 0.5);
  height: 64px !important;
  width: 100% !important;
  position: sticky;
  top: 0;
  z-index: 100;
  box-sizing: border-box;
  margin: 0;
  padding: 0;
  flex-shrink: 0;
  box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 1px 2px 0 rgba(0, 0, 0, 0.03);
  transition: all 0.3s ease;
}

.header:hover {
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.08), 0 2px 4px -1px rgba(0, 0, 0, 0.04);
}

.header-content {
  @apply flex items-center justify-between;
  height: 100%;
  padding: 0 24px;
  max-width: 100%;
}

.header-left {
  @apply flex items-center flex-1;
  min-width: 0;
}

.breadcrumb {
  @apply text-sm;
}

:deep(.el-breadcrumb__inner) {
  @apply font-medium text-gray-600;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}

:deep(.el-breadcrumb__inner.is-link) {
  @apply text-gray-500;
  transition: color 0.2s;
}

:deep(.el-breadcrumb__inner.is-link:hover) {
  color: #667eea;
  transform: translateX(2px);
}

:deep(.el-breadcrumb__separator) {
  @apply text-gray-400 mx-2;
}

.breadcrumb-icon {
  @apply text-gray-500;
  font-size: 16px;
  transition: all 0.2s ease;
}

:deep(.el-breadcrumb__inner.is-link:hover) .breadcrumb-icon {
  color: #667eea;
  transform: scale(1.1);
}

.header-right {
  @apply flex items-center gap-3;
  flex-shrink: 0;
}

.user-dropdown {
  @apply cursor-pointer;
}

.user-info {
  @apply flex items-center gap-3 cursor-pointer;
  padding: 8px 16px;
  border-radius: 12px;
  transition: all 0.3s ease;
  border: 1px solid transparent;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(249, 250, 251, 0.9));
}

.user-info:hover {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.08), rgba(118, 75, 162, 0.05));
  border-color: rgba(102, 126, 234, 0.2);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
  transform: translateY(-1px);
}

.avatar {
  background: var(--gradient-primary);
  @apply text-white;
  flex-shrink: 0;
  box-shadow: 0 4px 8px rgba(102, 126, 234, 0.3);
  transition: all 0.3s ease;
}

.user-info:hover .avatar {
  box-shadow: 0 6px 12px rgba(102, 126, 234, 0.4);
  transform: scale(1.05);
}

.user-details {
  @apply flex flex-col items-start;
  min-width: 0;
}

.username {
  @apply text-gray-900 font-semibold text-sm;
  line-height: 1.3;
  white-space: nowrap;
}

.user-role {
  @apply text-gray-500 text-xs;
  line-height: 1.3;
  margin-top: 2px;
}

.dropdown-icon {
  @apply text-gray-400;
  font-size: 14px;
  transition: all 0.3s ease;
  flex-shrink: 0;
  margin-left: 4px;
}

.user-info:hover .dropdown-icon {
  color: #667eea;
  transform: translateY(2px);
}

.user-menu {
  @apply mt-2;
  min-width: 180px;
  border-radius: 12px;
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.12);
  border: 1px solid rgba(229, 231, 235, 0.8);
  overflow: hidden;
}

.menu-item {
  @apply flex items-center gap-3;
  padding: 12px 20px;
  transition: all 0.2s ease;
}

.menu-item:hover {
  background: linear-gradient(90deg, rgba(102, 126, 234, 0.08), rgba(118, 75, 162, 0.05));
}

.menu-item :deep(.el-icon) {
  font-size: 18px;
  color: #667eea;
  transition: transform 0.2s ease;
}

.menu-item:hover :deep(.el-icon) {
  transform: scale(1.1);
}

.menu-item :deep(span) {
  @apply text-sm font-medium;
}

.logout-item {
  border-top: 1px solid rgba(229, 231, 235, 0.8);
}

.logout-item :deep(.el-icon) {
  color: #ef4444;
}

.logout-item:hover {
  background: linear-gradient(90deg, rgba(239, 68, 68, 0.08), rgba(220, 38, 38, 0.05));
}
</style>
