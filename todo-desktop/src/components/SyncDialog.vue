<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { app } from "../state";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const token = ref("");
const configured = ref(false);
const lastAt = ref<string | null>(null);
const lastMessage = ref<string | null>(null);
const busy = ref(false);
const notice = ref("");
const failed = ref(false);

async function refresh() {
  try {
    const [has, at, message] = await invoke<[boolean, string | null, string | null]>(
      "sync_status",
    );
    configured.value = has;
    lastAt.value = at;
    lastMessage.value = message;
  } catch {
    notice.value = "读取同步状态失败。";
    failed.value = true;
  }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    token.value = "";
    notice.value = "";
    failed.value = false;
    await refresh();
  },
);

async function saveToken() {
  busy.value = true;
  notice.value = "";
  failed.value = false;
  try {
    configured.value = await invoke<boolean>("sync_save_token", { token: token.value });
    token.value = "";
    notice.value = configured.value ? "Token 已加密保存到本机。" : "已清除 Token。";
  } catch (error: unknown) {
    notice.value =
      (error as { message?: string })?.message ?? "保存 Token 失败，请重试。";
    failed.value = true;
  } finally {
    busy.value = false;
  }
}

async function runSync() {
  busy.value = true;
  notice.value = "";
  failed.value = false;
  try {
    const report = await invoke<{ tasks: number; labels: number; uploaded: boolean }>(
      "sync_run",
    );
    notice.value = `同步完成：${report.tasks} 条事项 / ${report.labels} 个标签${
      report.uploaded ? "，已上传" : "，远端无变化"
    }`;
    await refresh();
    await app.refresh();
  } catch (error: unknown) {
    notice.value = (error as { message?: string })?.message ?? "同步失败，请重试。";
    failed.value = true;
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  if (props.open) void refresh();
});
</script>

<template>
  <div v-if="open" class="modal-backdrop">
    <section class="editor narrow panel" role="dialog" aria-modal="true">
      <header class="panel-head">
        <h2>数据同步</h2>
        <button class="quiet" aria-label="关闭" @click="emit('close')">×</button>
      </header>
      <div class="editor-form">
        <p class="muted sync-hint">
          与主应用共用私有仓库 <code>Nitinool/Agent-System-data</code> 的
          <code>sync/v2/task-notes.json</code>，Token 只经 Windows DPAPI 加密存在本机。
        </p>
        <p>
          <strong>{{
            configured ? "已配置 Token" : "还没有配置 Token"
          }}</strong>
          <span v-if="lastAt" class="muted">
            · 上次同步 {{ lastAt.slice(5, 16).replace("T", " ") }}</span
          >
        </p>
        <p v-if="lastMessage" class="muted sync-hint">{{ lastMessage }}</p>

        <label
          >Fine-grained Token（Contents 读写）
          <input
            v-model="token"
            type="password"
            autocomplete="off"
            placeholder="github_pat_…"
            :disabled="busy"
          />
        </label>
        <div class="actions">
          <button type="button" :disabled="busy" @click="saveToken">
            {{ configured ? "更新 / 清除 Token" : "保存 Token" }}
          </button>
          <span class="grow" />
          <button
            type="button"
            class="primary"
            :disabled="busy || !configured"
            @click="runSync"
          >
            {{ busy ? "同步中…" : "立即同步" }}
          </button>
        </div>
        <p v-if="notice" :class="failed ? 'error' : 'muted'">{{ notice }}</p>
        <p class="muted sync-hint">
          清空输入框再点保存即可删除本机 Token。同步按事项的更新时间取新的那条，删除会作为回收站记录同步过去。
        </p>
      </div>
    </section>
  </div>
</template>
