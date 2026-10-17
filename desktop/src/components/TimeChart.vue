<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { init, use, type ECharts } from 'echarts/core'
import { PieChart, BarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { duration } from '../domain'
use([PieChart, BarChart, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])
const props = defineProps<{ data: { name: string; value: number }[]; bar?: boolean }>()
const element = ref<HTMLElement>()
let chart: ECharts | undefined
let observer: ResizeObserver | undefined
function render() {
  chart?.setOption(
    {
      animation: false,
      tooltip: {
        trigger: props.bar ? 'axis' : 'item',
        formatter: props.bar
          ? undefined
          : (p: { name: string; value: number; percent: number }) =>
              `${p.name}：${duration(p.value)}（${p.percent}%）`,
      },
      legend: props.bar
        ? undefined
        : { type: 'scroll', orient: 'vertical', right: 8, top: 10, bottom: 10 },
      grid: { left: 60, right: 16, top: 12, bottom: 30 },
      xAxis: props.bar ? { type: 'category', data: props.data.map((d) => d.name) } : undefined,
      yAxis: props.bar ? { type: 'value' } : undefined,
      series: [
        {
          type: props.bar ? 'bar' : 'pie',
          radius: props.bar ? undefined : ['42%', '72%'],
          center: props.bar ? undefined : ['32%', '50%'],
          label: { show: false },
          data: props.data,
        },
      ],
    },
    true,
  )
}
onMounted(() => {
  if (element.value) {
    chart = init(element.value)
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(element.value)
    render()
  }
})
watch(() => props.data, render, { deep: true })
onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
})
</script>
<template>
  <div v-if="!data.length" class="empty chart-empty">当天暂无记录</div>
  <div v-show="data.length" ref="element" class="chart" role="img" aria-label="时间分配图" />
</template>
