import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/dashboard.vue')
  },
  {
    path: '/downloads',
    name: 'Downloads',
    component: () => import('@/views/downloads.vue')
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('@/views/tasks.vue')
  },
  {
    path: '/status',
    name: 'Status',
    component: () => import('@/views/status.vue')
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/settings.vue')
  },
  {
    path: '/system',
    name: 'System',
    component: () => import('@/views/system.vue')
  }
]

export const router = createRouter({
  history: createWebHistory(),
  routes
})
