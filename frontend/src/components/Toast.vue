<template>
  <transition name="toast">
    <div v-if="visible" class="fixed top-6 left-0 right-0 z-[9999] flex justify-center">
      <div
        class="flex items-center gap-3 px-5 py-4 rounded-2xl shadow-xl border backdrop-blur-md min-w-[260px]"
        :class="toastClass"
      >
        <!-- 成功图标 -->
        <CheckCircle2 v-if="type === 'success'" class="w-5 h-5" />

        <!-- 错误图标 -->
        <AlertCircle v-else class="w-5 h-5" />

        <span class="text-sm font-medium">
          {{ message }}
        </span>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, AlertCircle } from 'lucide-vue-next'

interface Props {
  visible: boolean
  message: string
  type: 'success' | 'error'
}

const props = withDefaults(defineProps<Props>(), {
  type: 'success',
})

const toastClass = computed(() => {
  return props.type === 'success'
    ? ['bg-emerald-50', 'border-emerald-200', 'text-emerald-700']
    : ['bg-rose-50', 'border-rose-200', 'text-rose-700']
})
</script>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition:
    opacity 0.3s ease,
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* 从顶部向下弹入 */
.toast-enter-from {
  opacity: 0;
  transform: translateY(-60px);
}

.toast-enter-to {
  opacity: 1;
  transform: translateY(0);
}

/* 向上离开 */
.toast-leave-from {
  opacity: 1;
  transform: translateY(0);
}

.toast-leave-to {
  opacity: 0;
  transform: translateY(-40px);
}
</style>
