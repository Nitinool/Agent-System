<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from "vue";
import { app } from "../state";
import { colors } from "../domain";

const props = withDefaults(
  defineProps<{
    open: boolean;
    kind: "project" | "section" | "label";
    id: string | null;
    projectId?: string | null;
  }>(),
  { projectId: null },
);
const emit = defineEmits<{ close: [] }>();

const form = reactive({ name: "", color: colors[0], favorite: false });
const initial = ref("");
const discarding = ref(false);
const deleting = ref(false);
const nameInput = ref<HTMLInputElement>();

const existing = computed(() => {
  const snapshot = app.snapshot.value;
  if (!props.id) return null;
  if (props.kind === "project")
    return snapshot.projects.find((project) => project.id === props.id) ?? null;
  if (props.kind === "section")
    return snapshot.sections.find((section) => section.id === props.id) ?? null;
  return snapshot.labels.find((label) => label.id === props.id) ?? null;
});
const dirty = computed(() => JSON.stringify(form) !== initial.value);
const title = computed(
  () =>
    `${props.id ? "编辑" : "新建"}${props.kind === "project" ? "项目" : props.kind === "section" ? "分区" : "标签"}`,
);

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    form.name = existing.value?.name ?? "";
    form.color =
      existing.value && "color" in existing.value
        ? existing.value.color
        : colors[0];
    form.favorite =
      existing.value && "favorite" in existing.value
        ? Boolean(existing.value.favorite)
        : false;
    initial.value = JSON.stringify(form);
    discarding.value = false;
    deleting.value = false;
    app.state.error = "";
    await nextTick();
    nameInput.value?.focus();
  },
);

function close() {
  if (dirty.value) discarding.value = true;
  else emit("close");
}
async function save() {
  const command =
    props.kind === "project"
      ? {
          type: "project_save" as const,
          id: props.id,
          draft: { name: form.name, color: form.color, favorite: form.favorite },
        }
      : props.kind === "section"
        ? {
            type: "section_save" as const,
            id: props.id,
            project_id: props.projectId ?? "",
            name: form.name,
          }
        : {
            type: "label_save" as const,
            id: props.id,
            draft: { name: form.name, color: form.color },
          };
  if (await app.change(command)) emit("close");
}
async function remove() {
  if (!props.id) return;
  const command =
    props.kind === "project"
      ? ({ type: "project_delete", id: props.id } as const)
      : props.kind === "section"
        ? ({ type: "section_delete", id: props.id } as const)
        : ({ type: "label_delete", id: props.id } as const);
  if (await app.change(command)) emit("close");
}
</script>

<template>
  <div v-if="open" class="modal-backdrop">
    <section class="editor narrow panel" role="dialog" aria-modal="true">
      <header class="panel-head">
        <h2>{{ title }}</h2>
        <button class="quiet" aria-label="关闭" @click="close">×</button>
      </header>
      <form class="editor-form" @submit.prevent="save">
        <label
          >{{ kind === "section" ? "分区名称" : kind === "project" ? "项目名称" : "标签名称" }}<input
            ref="nameInput"
            v-model="form.name"
            required
            :maxlength="kind === 'project' ? 100 : 40"
            :disabled="app.state.loading"
            autocomplete="off"
        /></label>
        <fieldset v-if="kind !== 'section'">
          <legend>颜色</legend>
          <div class="swatches">
            <label
              v-for="color in colors"
              :key="color"
              class="swatch"
              :style="{ background: color }"
              ><input
                v-model="form.color"
                type="radio"
                :value="color"
                :aria-label="'颜色 ' + color"
              /><span v-if="color === form.color">✓</span></label
            >
          </div>
        </fieldset>
        <label v-if="kind === 'project'" class="inline-label check">
          <input v-model="form.favorite" type="checkbox" :disabled="app.state.loading" />
          固定到侧边栏顶部
        </label>
        <p v-if="app.state.error" class="error" role="alert">{{ app.state.error }}</p>
        <div v-if="deleting" class="confirmation" role="alert">
          <span>确定删除这个{{ kind === "project" ? "项目" : kind === "section" ? "分区" : "标签" }}？</span
          ><button type="button" class="danger" :disabled="app.state.loading" @click="remove">
            确认删除</button
          ><button type="button" @click="deleting = false">返回</button>
        </div>
        <div v-else-if="discarding" class="confirmation" role="alert">
          <span>有未保存内容</span
          ><button type="button" @click="emit('close')">放弃修改</button
          ><button type="button" @click="discarding = false">继续编辑</button>
        </div>
        <footer>
          <button
            v-if="id"
            type="button"
            class="quiet danger"
            :disabled="app.state.loading"
            @click="deleting = true"
          >
            删除</button
          ><span class="grow" /><button type="button" @click="close">取消</button
          ><button class="primary" :disabled="app.state.loading || !app.state.ready">
            {{ app.state.loading ? "保存中…" : "保存" }}
          </button>
        </footer>
      </form>
    </section>
  </div>
</template>
