<template>
  <el-container class="app-layout">
    <AppSidebar @collapse-change="handleCollapseChange" />
    <el-container class="main-container" :style="{ marginLeft: sidebarWidth }">
      <AppHeader />
      <el-main class="main-content">
        <router-view v-slot="{ Component }">
          <Suspense>
            <component :is="Component" />
            <template #fallback>
              <div class="loading-container">
                <el-skeleton :rows="8" animated />
              </div>
            </template>
          </Suspense>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import AppSidebar from './app-sidebar.vue'
import AppHeader from './app-header.vue'

const isCollapsed = ref(false)

const sidebarWidth = computed(() => {
  return isCollapsed.value ? '64px' : '240px'
})

function handleCollapseChange(collapsed: boolean) {
  isCollapsed.value = collapsed
}
</script>

<style scoped>
.app-layout {
  @apply min-h-screen;
  background: linear-gradient(135deg, #f5f7fa 0%, #e8eaf6 50%, #f3e5f5 100%);
  position: relative;
}

.app-layout::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-image: 
    radial-gradient(circle at 20% 50%, rgba(102, 126, 234, 0.03) 0%, transparent 50%),
    radial-gradient(circle at 80% 80%, rgba(118, 75, 162, 0.03) 0%, transparent 50%);
  pointer-events: none;
}

.main-container {
  @apply transition-all duration-300 ease-in-out;
  min-height: 100vh;
  width: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 1;
}

:deep(.el-container.main-container) {
  width: 100%;
  max-width: 100%;
  overflow-x: hidden;
}

:deep(.el-header) {
  width: 100% !important;
  max-width: 100%;
  padding: 0;
  margin: 0;
}

.main-content {
  @apply p-6;
  min-height: calc(100vh - 64px);
  animation: fadeIn 0.4s ease-out;
}

.loading-container {
  @apply p-6;
  animation: pulse 1.5s ease-in-out infinite;
}
</style>
