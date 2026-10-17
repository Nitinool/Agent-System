<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { NConfigProvider, NModal, zhCN, dateZhCN } from 'naive-ui'
import {
  House,
  CalendarDays,
  Layers,
  Clock,
  Briefcase,
  Wallet,
  PanelLeftClose,
  Settings,
  Play,
  Pause,
} from 'lucide-vue-next'
import { useApp } from './state'
import { call, subscribe } from './bridge'
import { today } from './domain'
import Editor from './components/Editor.vue'
import SyncSettings from './components/SyncSettings.vue'
const app = useApp(),
  collapsed = ref(false)
const nav = [
  ['/', '今日', House],
  ['/tasks', '事项', CalendarDays],
  ['/projects', '项目', Layers],
  ['/records', '时间记录', Clock],
  ['/jobs', '求职', Briefcase],
  ['/finance', '财务', Wallet],
] as const
let stops: (() => void)[] = [],
  timer: ReturnType<typeof setInterval> | undefined
watch(
  () => app.noteDraft,
  () => call('set_editing', { editing: !!app.editor || !!app.noteDraft }).catch(() => {}),
)
onMounted(async () => {
  await Promise.all([app.refresh(), app.statuses()])
  for (const [event, action] of [
    ['data-changed', app.refresh],
    [
      'sync-changed',
      async () => {
        await app.statuses()
        await app.refresh()
      },
    ],
    ['capture-changed', app.statuses],
  ] as const) {
    stops.push(await subscribe(event, action))
  }
  timer = setInterval(() => {
    app.day = today()
  }, 30000)
  await call('app_ready').catch(() => {})
})
onBeforeUnmount(() => {
  stops.forEach((stop) => stop())
  if (timer) clearInterval(timer)
})
</script>
<template>
  <NConfigProvider
    :locale="zhCN"
    :date-locale="dateZhCN"
    :theme-overrides="{
      common: {
        primaryColor: '#2563eb',
        primaryColorHover: '#1d4ed8',
        borderRadius: '5px',
        fontSize: '14px',
        heightMedium: '32px',
      },
      DataTable: { tdPaddingMedium: '6px 10px' },
    }"
  >
    <div class="shell" :class="{ collapsed }">
      <aside class="sidebar">
        <div class="brand">
          <span class="brand-mark">A</span><strong v-if="!collapsed">我的记录</strong>
        </div>
        <nav>
          <RouterLink
            v-for="[path, label, icon] in nav"
            :key="path"
            :to="path"
            :title="label"
            :aria-label="label"
            :class="{ active: $route.path === path }"
            ><component :is="icon" :size="18" /><span v-if="!collapsed">{{
              label
            }}</span></RouterLink
          >
        </nav>
        <div class="sidebar-bottom">
          <button :title="app.capture.message" @click="app.toggleCapture">
            <component :is="app.capture.running ? Pause : Play" :size="16" /><span
              v-if="!collapsed"
              >{{ app.capture.running ? '暂停记录' : '开始记录' }}</span
            ></button
          ><button @click="app.settingsOpen = true" title="数据同步与设置">
            <Settings :size="17" /><span v-if="!collapsed">数据同步</span></button
          ><small v-if="!collapsed" class="sync-summary"
            >本机待同步 {{ app.sync.pending }} 条<br />{{ app.sync.message }}<br />{{
              app.sync.settings.auto_sync ? '自动' : '手动'
            }}同步</small
          ><button title="收起或展开导航" @click="collapsed = !collapsed">
            <PanelLeftClose :size="17" /><span v-if="!collapsed">收起导航</span>
          </button>
        </div>
      </aside>
      <main><RouterView /></main>
      <footer>
        <span class="status-dot" :class="{ running: app.capture.running }" />{{ app.capture.message
        }}<span class="feedback" role="status" :class="{ error: app.error }">{{
          app.error || app.notice
        }}</span
        ><button v-if="app.undo" class="quiet" @click="app.undoCompletion">撤销完成操作</button
        ><span class="version">V2 · 本地优先</span>
      </footer>
    </div>
    <Editor /><SyncSettings />
    <NModal
      :show="!!app.deleting"
      preset="dialog"
      title="删除记录"
      content="删除将同步到新版的另一台电脑。确认删除？"
      positive-text="删除"
      negative-text="取消"
      @negative-click="app.deleting = null"
      @close="app.deleting = null"
      @positive-click="
        async () => {
          if (app.deleting && (await app.change({ type: 'delete', uid: app.deleting }))) {
            if(app.editor?.uid===app.deleting) await app.openEditor(null)
            app.deleting = null
          }
        }
      "
    />
  </NConfigProvider>
</template>
