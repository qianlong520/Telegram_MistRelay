import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    isLoading: false
  }),
  actions: {
    setLoading(loading: boolean) {
      this.isLoading = loading
    }
  }
})
