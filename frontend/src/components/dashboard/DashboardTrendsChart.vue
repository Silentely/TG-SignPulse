<script setup lang="ts">
/**
 * 仪表盘：签到运行历史趋势与成功率统计图表（SVG 纯前端渲染，零第三方图表库依赖）。
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { TrendingUp, Calendar } from 'lucide-vue-next'
import { getHistoryTrends, type TrendsResponse } from '../../lib/api'
import { withToken } from '../../lib/api/core'
import { useLatestResponseGuard } from '../../lib/latest-response'

const selectedDays = ref<number>(7)
const loading = ref<boolean>(true)
const trendsData = ref<TrendsResponse | null>(null)
const hoveredIndex = ref<number | null>(null)
// 7/30 天快速切换会并发多个请求，慢的那个先返回会覆盖新数据
const trendsGuard = useLatestResponseGuard()

const loadTrends = async () => {
  const seq = trendsGuard.next()
  loading.value = true
  try {
    const res = await withToken((token) => getHistoryTrends(token, selectedDays.value))
    if (!trendsGuard.isCurrent(seq)) return // 过期响应：已切换到其他天数
    trendsData.value = res ?? null
  } catch {
    if (!trendsGuard.isCurrent(seq)) return
    trendsData.value = null
  } finally {
    if (trendsGuard.isCurrent(seq)) loading.value = false
  }
}

onMounted(() => {
  loadTrends()
})

onUnmounted(() => {
  trendsGuard.invalidate()
})

watch(selectedDays, () => {
  loadTrends()
})

const daysOptions = [
  { label: '7 天', value: 7 },
  { label: '30 天', value: 30 },
]

const maxTotal = computed(() => {
  if (!trendsData.value?.trends?.length) return 10
  const max = Math.max(...trendsData.value.trends.map(d => d.total))
  return max > 0 ? max : 10
})

// SVG 画布尺寸
const svgWidth = 600
const svgHeight = 160
const padding = { top: 20, right: 20, bottom: 28, left: 30 }
const chartWidth = svgWidth - padding.left - padding.right
const chartHeight = svgHeight - padding.top - padding.bottom

const points = computed(() => {
  if (!trendsData.value?.trends?.length) return []
  const list = trendsData.value.trends
  const step = chartWidth / Math.max(list.length - 1, 1)

  return list.map((item, idx) => {
    const x = padding.left + idx * step
    const barH = (item.total / maxTotal.value) * chartHeight
    const barY = padding.top + chartHeight - barH
    const rateY = padding.top + (1 - item.success_rate) * chartHeight

    return {
      ...item,
      x,
      barH,
      barY,
      rateY,
      shortDate: item.date.slice(5),
    }
  })
})

const ratePathD = computed(() => {
  if (points.value.length === 0) return ''
  return points.value.reduce((acc, p, idx) => {
    return idx === 0 ? `M ${p.x} ${p.rateY}` : `${acc} L ${p.x} ${p.rateY}`
  }, '')
})

const hoveredPoint = computed(() => {
  if (hoveredIndex.value === null) return null
  return points.value[hoveredIndex.value] || null
})
</script>

<template>
  <div class="ui-card p-4 sm:p-5 flex flex-col gap-4">
    <!-- 头部标题与切换 -->
    <div class="flex items-center justify-between flex-wrap gap-2">
      <div class="flex items-center gap-2">
        <span class="ui-section-icon">
          <TrendingUp class="w-3.5 h-3.5 text-sky-500" stroke-width="2" />
        </span>
        <span class="text-sm font-medium text-gray-900 dark:text-gray-100">签到执行与成功率趋势</span>
      </div>

      <!-- 7天 / 30天 切换 -->
      <div class="inline-flex items-center bg-gray-100 dark:bg-white/[0.05] p-0.5 rounded text-xs">
        <button
          v-for="opt in daysOptions"
          :key="opt.value"
          type="button"
          class="px-2.5 py-1 rounded-sm font-medium transition-colors"
          :class="selectedDays === opt.value
            ? 'bg-white dark:bg-gray-800 text-sky-600 dark:text-sky-400 shadow-xs'
            : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
          @click="selectedDays = opt.value"
        >
          {{ opt.label }}
        </button>
      </div>
    </div>

    <!-- 指标汇总一览 -->
    <div class="grid grid-cols-3 gap-2 sm:gap-3 py-1">
      <div class="bg-gray-50/80 dark:bg-white/[0.02] border border-gray-100 dark:border-gray-800/60 p-2.5 rounded">
        <span class="text-[11px] text-gray-500 block mb-1">期间执行总计</span>
        <span class="text-lg sm:text-xl font-mono font-semibold text-gray-900 dark:text-gray-100">
          {{ trendsData?.total_runs ?? 0 }}
        </span>
      </div>
      <div class="bg-gray-50/80 dark:bg-white/[0.02] border border-gray-100 dark:border-gray-800/60 p-2.5 rounded">
        <span class="text-[11px] text-gray-500 block mb-1">综合成功率</span>
        <span class="text-lg sm:text-xl font-mono font-semibold text-emerald-600 dark:text-emerald-400">
          {{ trendsData ? Math.round(trendsData.overall_success_rate * 100) : 100 }}%
        </span>
      </div>
      <div class="bg-gray-50/80 dark:bg-white/[0.02] border border-gray-100 dark:border-gray-800/60 p-2.5 rounded">
        <span class="text-[11px] text-gray-500 block mb-1">失败或异常</span>
        <span
          class="text-lg sm:text-xl font-mono font-semibold"
          :class="(trendsData?.total_failed ?? 0) > 0 ? 'text-rose-500' : 'text-gray-700 dark:text-gray-300'"
        >
          {{ trendsData?.total_failed ?? 0 }}
        </span>
      </div>
    </div>

    <!-- SVG 趋势图表区 -->
    <div v-if="loading" class="h-44 flex items-center justify-center">
      <div class="ui-skeleton h-36 w-full rounded" />
    </div>

    <div v-else-if="!trendsData || trendsData.trends.length === 0" class="ui-empty !py-8">
      <Calendar class="w-8 h-8 mx-auto text-gray-300 dark:text-gray-600 mb-2" />
      <p class="ui-empty-desc">暂无近 {{ selectedDays }} 天签到数据</p>
    </div>

    <div v-else class="relative w-full overflow-hidden">
      <!-- 悬停信息浮层 -->
      <div
        v-if="hoveredPoint"
        class="absolute top-1 left-1/2 -translate-x-1/2 bg-gray-900/90 dark:bg-gray-800/95 text-white text-[11px] px-3 py-1.5 rounded shadow-lg backdrop-blur-xs flex items-center gap-3 pointer-events-none z-10 font-mono"
      >
        <span class="text-gray-300">{{ hoveredPoint.date }}</span>
        <span>执行: <b>{{ hoveredPoint.total }}</b></span>
        <span class="text-emerald-400">成功: <b>{{ hoveredPoint.success }}</b></span>
        <span v-if="hoveredPoint.failed > 0" class="text-rose-400">失败: <b>{{ hoveredPoint.failed }}</b></span>
        <span class="text-sky-300">成功率: <b>{{ Math.round(hoveredPoint.success_rate * 100) }}%</b></span>
      </div>

      <!-- SVG 主体 -->
      <svg
        :viewBox="`0 0 ${svgWidth} ${svgHeight}`"
        class="w-full h-44 overflow-visible select-none"
        @mouseleave="hoveredIndex = null"
      >
        <!-- 背景辅助水平网格线 -->
        <line
          :x1="padding.left"
          :y1="padding.top"
          :x2="svgWidth - padding.right"
          :y2="padding.top"
          class="stroke-gray-200 dark:stroke-gray-800/60"
          stroke-dasharray="3 3"
        />
        <line
          :x1="padding.left"
          :y1="padding.top + chartHeight / 2"
          :x2="svgWidth - padding.right"
          :y2="padding.top + chartHeight / 2"
          class="stroke-gray-200 dark:stroke-gray-800/60"
          stroke-dasharray="3 3"
        />
        <line
          :x1="padding.left"
          :y1="padding.top + chartHeight"
          :x2="svgWidth - padding.right"
          :y2="padding.top + chartHeight"
          class="stroke-gray-200 dark:stroke-gray-800"
        />

        <!-- 柱状图（执行次数） -->
        <g v-for="(p, idx) in points" :key="`bar-${p.date}`">
          <!-- 背景触发区域（扩大 hover 范围） -->
          <rect
            :x="p.x - 14"
            :y="padding.top"
            width="28"
            :height="chartHeight"
            class="fill-transparent cursor-pointer"
            @mouseenter="hoveredIndex = idx"
          />

          <!-- 成功柱条 -->
          <rect
            :x="p.x - (selectedDays === 30 ? 3 : 6)"
            :y="p.barY"
            :width="selectedDays === 30 ? 6 : 12"
            :height="p.barH"
            class="transition-all duration-200 cursor-pointer"
            :class="hoveredIndex === idx
              ? 'fill-sky-500'
              : 'fill-sky-400/40 dark:fill-sky-500/30'"
            rx="2"
            @mouseenter="hoveredIndex = idx"
          />

          <!-- X 轴日期文字 -->
          <text
            v-if="selectedDays === 7 || idx % 4 === 0 || idx === points.length - 1"
            :x="p.x"
            :y="svgHeight - 8"
            text-anchor="middle"
            class="text-[10px] fill-gray-400 font-mono"
          >
            {{ p.shortDate }}
          </text>
        </g>

        <!-- 成功率平滑折线 -->
        <path
          :d="ratePathD"
          fill="none"
          class="stroke-emerald-500 dark:stroke-emerald-400 transition-all duration-300"
          stroke-width="2"
          stroke-linejoin="round"
          stroke-linecap="round"
        />

        <!-- 折线圆点 -->
        <circle
          v-for="(p, idx) in points"
          :key="`dot-${p.date}`"
          :cx="p.x"
          :cy="p.rateY"
          :r="hoveredIndex === idx ? 4.5 : 2.5"
          class="transition-all duration-200 pointer-events-none"
          :class="hoveredIndex === idx
            ? 'fill-emerald-400 stroke-white dark:stroke-gray-900'
            : 'fill-emerald-500'"
          stroke-width="1.5"
        />
      </svg>
    </div>

    <!-- 底部图例说明 -->
    <div class="flex items-center justify-between text-[11px] text-gray-500 border-t border-gray-100 dark:border-gray-800/60 pt-2.5">
      <div class="flex items-center gap-4">
        <div class="flex items-center gap-1.5">
          <span class="w-2.5 h-2.5 rounded-xs bg-sky-400/60 dark:bg-sky-500/40" />
          <span>执行总数</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="w-2.5 h-1 rounded-full bg-emerald-500" />
          <span>成功率趋势</span>
        </div>
      </div>
      <div v-if="trendsData?.categories && Object.keys(trendsData.categories).length > 0" class="hidden sm:flex items-center gap-2">
        <span class="text-gray-400">常见故障:</span>
        <span
          v-for="(count, cat) in trendsData.categories"
          :key="cat"
          class="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/[0.05] text-[10px] font-mono text-gray-600 dark:text-gray-300"
        >
          {{ cat }}: {{ count }}
        </span>
      </div>
    </div>
  </div>
</template>
