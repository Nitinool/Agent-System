<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from "vue";
import type { Task } from "../bindings/Task";
import type { TaskDraft } from "../bindings/TaskDraft";
import { app } from "../state";
import {
  colors,
  newDraft,
  parentOptions,
  priorityColor,
  priorityName,
  priorityTitle,
  shiftDay,
} from "../domain";

const props = withDefaults(
  defineProps<{
    open: boolean;
    task: Task | null;
    projectId?: string | null;
    parentId?: string | null;
  }>(),
  { projectId: null, parentId: null },
);
const emit = defineEmits<{ close: [] }>();

const f = reactive<TaskDraft>(newDraft());
const initial = ref("");
const discard = ref(false);
const deleting = ref(false);
const nameInput = ref<HTMLInputElement>();

const dirty = computed(() => JSON.stringify(f) !== initial.value);
// 项目 / 分区这一层暂时从界面撤掉，数据仍保留；父事项不限项目，选中后自动跟随父事项的项目。
const parentChoices = computed(() =>
  parentOptions(
    app.snapshot.value.tasks.filter((task) => task.id !== props.task?.id),
    props.task?.id ?? null,
  ),
);

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    Object.assign(
      f,
      props.task
        ? {
            title: props.task.title,
            notes: props.task.notes,
            color: props.task.color,
            priority: props.task.priority,
            start: props.task.start,
            end: props.task.end === props.task.start ? null : props.task.end,
            project_id: props.task.project_id,
            section_id: props.task.section_id,
            parent_id: props.task.parent_id,
            label_ids: [...props.task.label_ids],
          }
        : {
            ...newDraft(
              app.state.day,
              colors[app.snapshot.value.tasks.length % colors.length],
            ),
            project_id: props.projectId,
            parent_id: props.parentId,
          },
    );
    initial.value = JSON.stringify(f);
    discard.value = false;
    deleting.value = false;
    app.state.error = "";
    await nextTick();
    nameInput.value?.focus();
  },
);

function setParent(value: string) {
  f.parent_id = value || null;
  if (!f.parent_id) return;
  const parent = app.snapshot.value.tasks.find((task) => task.id === f.parent_id);
  if (parent && parent.project_id !== f.project_id) {
    f.project_id = parent.project_id;
    f.section_id = parent.section_id;
  }
}
function close() {
  if (dirty.value) discard.value = true;
  else emit("close");
}
async function save() {
  if (
    await app.change({
      type: "task_save",
      id: props.task?.id ?? null,
      draft: { ...f, start: f.start || null, end: f.end || null },
    })
  )
    emit("close");
}
async function remove() {
  if (props.task && (await app.change({ type: "task_delete", id: props.task.id })))
    emit("close");
}
function preset(days: number) {
  f.start = app.state.day;
  f.end = days === 1 ? null : shiftDay(app.state.day, days - 1);
}
function keyboard(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
  }
  if (event.key === "Tab") {
    const dialog = event.currentTarget as HTMLElement;
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        "button:not(:disabled),input:not(:disabled),select,textarea",
      ),
    ).filter((element) => !element.hasAttribute("disabled"));
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
}
</script>

<template>
  <div v-if="open" class="modal-backdrop">
    <section
      class="editor panel"
      role="dialog"
      aria-modal="true"
      :aria-label="task ? '编辑事项' : '新增事项'"
      @keydown="keyboard"
    >
      <header class="panel-head">
        <h2>{{ task ? "编辑事项" : "新增事项" }}</h2>
        <button
          class="quiet"
          aria-label="关闭编辑"
          :disabled="app.state.loading"
          @click="close"
        >
          ×
        </button>
      </header>
      <form class="editor-form" @submit.prevent="save">
        <label
          >事项名称<input
            ref="nameInput"
            v-model="f.title"
            required
            maxlength="200"
            :disabled="app.state.loading"
            autocomplete="off"
        /></label>

        <label
          >父事项<select
            :value="f.parent_id ?? ''"
            :disabled="app.state.loading"
            @change="setParent(($event.target as HTMLSelectElement).value)"
          >
            <option value="">无（顶层事项）</option>
            <option v-for="t in parentChoices" :key="t.id" :value="t.id">
              {{ t.title }}
            </option>
          </select></label
        >

        <fieldset>
          <legend>优先级</legend>
          <div class="priority-row">
            <label
              v-for="p in [1, 2, 3, 4]"
              :key="p"
              class="priority-option"
              :class="{ active: f.priority === p }"
              :title="priorityTitle(p)"
            >
              <input
                v-model.number="f.priority"
                type="radio"
                :value="p"
                :aria-label="priorityTitle(p)"
              />
              <span
                class="priority-dot"
                :style="{ background: priorityColor(p) }"
              />{{ priorityName(p) }}
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend>标签</legend>
          <div class="chips">
            <label
              v-for="label in app.snapshot.value.labels"
              :key="label.id"
              class="chip-input"
              :class="{ on: f.label_ids.includes(label.id) }"
              :style="{ '--chip': label.color }"
            >
              <input
                v-model="f.label_ids"
                type="checkbox"
                :value="label.id"
              /><span>{{ label.name }}</span>
            </label>
            <small v-if="!app.snapshot.value.labels.length" class="muted"
              >还没有标签，可在左侧「标签」里新建。</small
            >
          </div>
        </fieldset>

        <fieldset>
          <legend>安排日期</legend>
          <div class="preset-row">
            <button type="button" @click="preset(1)">今天</button
            ><button type="button" @click="preset(7)">一周</button
            ><button type="button" @click="preset(30)">一个月</button
            ><button
              type="button"
              class="quiet"
              @click="
                f.start = null;
                f.end = null;
              "
            >
              清除安排
            </button>
          </div>
          <div class="date-range">
            <label
              >开始日期<input
                type="date"
                aria-label="开始日期"
                v-model="f.start" /></label
            ><span>至</span
            ><label
              >结束日期<input
                type="date"
                aria-label="结束日期"
                v-model="f.end"
                :min="f.start || undefined"
            /></label>
          </div>
          <small class="muted"
            >结束日期留空表示单日；开始日期留空表示待安排。</small
          >
        </fieldset>

        <fieldset>
          <legend>事项颜色</legend>
          <div class="swatches">
            <label
              v-for="color in colors"
              :key="color"
              class="swatch"
              :style="{ background: color }"
              ><input
                type="radio"
                name="task-color"
                :value="color"
                v-model="f.color"
                :aria-label="'颜色 ' + color"
              /><span v-if="color === f.color">✓</span></label
            >
          </div>
        </fieldset>

        <label
          >备注<textarea
            v-model="f.notes"
            maxlength="50000"
            rows="4"
            placeholder="补充说明、想法或笔记…"
          />
        </label>

        <p v-if="app.state.error" class="error" role="alert">
          {{ app.state.error }}
        </p>
        <div v-if="deleting" class="confirmation" role="alert">
          <span>确定删除这条事项？子事项会一起删除。</span
          ><button
            type="button"
            class="danger"
            :disabled="app.state.loading"
            @click="remove"
          >
            确认删除</button
          ><button type="button" @click="deleting = false">返回</button>
        </div>
        <div v-else-if="discard" class="confirmation" role="alert">
          <span>有未保存内容</span
          ><button type="button" @click="emit('close')">放弃修改</button
          ><button type="button" @click="discard = false">继续编辑</button>
        </div>
        <footer>
          <button
            v-if="task"
            type="button"
            class="quiet danger"
            :disabled="app.state.loading"
            @click="deleting = true"
          >
            删除事项</button
          ><span class="grow" /><button
            type="button"
            :disabled="app.state.loading"
            @click="close"
          >
            取消</button
          ><button
            class="primary"
            :disabled="app.state.loading || !app.state.ready"
          >
            {{ app.state.loading ? "保存中…" : "保存" }}
          </button>
        </footer>
      </form>
    </section>
  </div>
</template>
