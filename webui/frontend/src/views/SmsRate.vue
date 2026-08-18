<script setup>
import { computed, onActivated, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSmsSuccessRate } from '@/api/sms'
import { fmtTime } from '@/api/request'

const loading = ref(false)
const byProvider = ref([])
const byManufacturer = ref([])
const records = ref([])

const totals = computed(() => {
  const total = byProvider.value.reduce((n, r) => n + Number(r.total || 0), 0)
  const success = byProvider.value.reduce((n, r) => n + Number(r.success || 0), 0)
  const failed = byProvider.value.reduce((n, r) => n + Number(r.failed || 0), 0)
  const decided = success + failed
  return {
    total,
    success,
    failed,
    pending: byProvider.value.reduce((n, r) => n + Number(r.pending || 0), 0),
    rate: decided ? (success * 100 / decided).toFixed(2) : '0.00',
  }
})

function rateText(row) {
  return `${Number(row.success_rate || 0).toFixed(2)}%`
}

async function load() {
  loading.value = true
  try {
    const r = await getSmsSuccessRate()
    byProvider.value = r.by_provider || []
    byManufacturer.value = r.by_manufacturer || []
    records.value = r.records || []
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

onActivated(() => load())
</script>

<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :xs="12" :sm="6" style="margin-bottom: 16px">
        <el-card shadow="hover"><div class="metric"><b>{{ totals.rate }}%</b><span>总成功率</span></div></el-card>
      </el-col>
      <el-col :xs="12" :sm="6" style="margin-bottom: 16px">
        <el-card shadow="hover"><div class="metric"><b>{{ totals.total }}</b><span>接码次数</span></div></el-card>
      </el-col>
      <el-col :xs="12" :sm="6" style="margin-bottom: 16px">
        <el-card shadow="hover"><div class="metric success"><b>{{ totals.success }}</b><span>成功</span></div></el-card>
      </el-col>
      <el-col :xs="12" :sm="6" style="margin-bottom: 16px">
        <el-card shadow="hover"><div class="metric danger"><b>{{ totals.failed }}</b><span>失败</span></div></el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>
        <div class="card-head">
          <span class="section-title" style="margin: 0">供应商成功率</span>
          <el-button size="small" :loading="loading" @click="load"><el-icon><Refresh /></el-icon>刷新</el-button>
        </div>
      </template>
      <el-table v-loading="loading" :data="byProvider" size="small" stripe :default-sort="{ prop: 'success_rate', order: 'descending' }">
        <el-table-column prop="provider" label="供应商" min-width="140" sortable />
        <el-table-column prop="total" label="总次数" width="110" sortable />
        <el-table-column prop="success" label="成功" width="100" sortable />
        <el-table-column prop="failed" label="失败" width="100" sortable />
        <el-table-column prop="pending" label="进行中" width="100" sortable />
        <el-table-column prop="success_rate" label="成功率" width="120" sortable>
          <template #default="{ row }"><el-tag type="success" effect="plain">{{ rateText(row) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="最近使用" width="170" sortable prop="last_started_at">
          <template #default="{ row }">{{ fmtTime(row.last_started_at) }}</template>
        </el-table-column>
        <template #empty><el-empty description="暂无接码记录" :image-size="70" /></template>
      </el-table>
    </el-card>

    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header><span class="section-title" style="margin: 0">厂家/号段成功率</span></template>
      <el-table v-loading="loading" :data="byManufacturer" size="small" stripe>
        <el-table-column prop="provider" label="供应商" min-width="120" sortable />
        <el-table-column prop="manufacturer" label="厂家/国家" min-width="150" sortable />
        <el-table-column prop="phone_prefix" label="号段" width="100" sortable />
        <el-table-column prop="total" label="总次数" width="100" sortable />
        <el-table-column prop="success" label="成功" width="90" sortable />
        <el-table-column prop="failed" label="失败" width="90" sortable />
        <el-table-column prop="success_rate" label="成功率" width="120" sortable>
          <template #default="{ row }"><el-tag type="success" effect="plain">{{ rateText(row) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="最近使用" width="170" sortable prop="last_started_at">
          <template #default="{ row }">{{ fmtTime(row.last_started_at) }}</template>
        </el-table-column>
        <template #empty><el-empty description="暂无厂家/号段统计" :image-size="70" /></template>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header><span class="section-title" style="margin: 0">最近接码明细</span></template>
      <el-table v-loading="loading" :data="records" size="small" stripe>
        <el-table-column prop="started_at" label="时间" width="170" sortable>
          <template #default="{ row }">{{ fmtTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column prop="provider" label="供应商" width="120" sortable />
        <el-table-column prop="manufacturer" label="厂家/国家" min-width="140" sortable />
        <el-table-column prop="phone_prefix" label="号段" width="100" sortable />
        <el-table-column prop="phone_masked" label="号码" width="130" sortable />
        <el-table-column prop="status" label="状态" width="100" sortable>
          <template #default="{ row }">
            <el-tag :type="row.status === 'success' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'" effect="plain">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip sortable />
        <el-table-column prop="reason" label="原因" min-width="180" show-overflow-tooltip />
        <template #empty><el-empty description="暂无接码明细" :image-size="70" /></template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
.metric { display: flex; flex-direction: column; gap: 4px; }
.metric b { font-size: 26px; color: var(--brand); line-height: 1; }
.metric span { color: var(--el-text-color-secondary); font-size: 13px; }
.metric.success b { color: var(--el-color-success); }
.metric.danger b { color: var(--el-color-danger); }
</style>
