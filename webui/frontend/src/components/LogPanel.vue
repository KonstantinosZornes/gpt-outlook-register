<script setup>
import { nextTick, onDeactivated, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { copyText } from '@/api/request'
import { useRuntimeStore } from '@/stores/runtime'

const runtime = useRuntimeStore()
const { logs } = storeToRefs(runtime)
const boxRef = ref(null)
const fullscreen = ref(false)

watch(
  () => logs.value.length,
  async () => {
    await nextTick()
    const el = boxRef.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

watch(fullscreen, async (v) => {
  if (v) {
    document.body.style.overflow = 'hidden'
    await nextTick()
    const el = boxRef.value
    if (el) el.scrollTop = el.scrollHeight
  } else {
    document.body.style.overflow = ''
  }
})

function onKey(e) {
  if (e.key === 'Escape' && fullscreen.value) fullscreen.value = false
}

window.addEventListener('keydown', onKey)
onDeactivated(() => {
  fullscreen.value = false
  document.body.style.overflow = ''
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})

async function copyAll() {
  const text = logs.value.map((l) => l.text).join('\n')
  if (!text) {
    ElMessage.warning('暂无日志')
    return
  }
  await copyText(text)
}
</script>

<template>
  <div class="log-wrap" :class="{ fullscreen }">
    <div class="log-head">
      <span class="section-title" style="margin: 0">实时日志</span>
      <div class="log-actions">
        <el-button size="small" text @click="copyAll">复制</el-button>
        <el-button size="small" text @click="fullscreen = !fullscreen">
          {{ fullscreen ? '退出全屏' : '全屏' }}
        </el-button>
        <el-button size="small" text @click="runtime.clearLogs">清空</el-button>
      </div>
    </div>
    <div ref="boxRef" class="log-box">
      <div v-for="l in logs" :key="l.id" class="line" :class="l.kind">{{ l.text }}</div>
      <div v-if="!logs.length" class="line" style="color: #8a7">等待日志输出…</div>
    </div>
  </div>
</template>

<style scoped>
.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.log-actions {
  display: flex;
  gap: 4px;
}
.log-wrap.fullscreen {
  position: fixed;
  inset: 0;
  z-index: 3000;
  margin: 0;
  padding: 12px 16px;
  background: var(--el-bg-color);
  display: flex;
  flex-direction: column;
}
.log-wrap.fullscreen .log-box {
  flex: 1;
  height: auto;
}
</style>
