import { computed, reactive, ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { Snapshot } from "./bindings/Snapshot";
import type { Mutation } from "./bindings/Mutation";
import { onDay, sortTasks, today } from "./domain";
const snapshot = ref<Snapshot>({
  revision: 0,
  projects: [],
  sections: [],
  labels: [],
  tasks: [],
});
const state = reactive({
  day: today(),
  loading: false,
  ready: false,
  error: "",
});
const todayTasks = computed(() =>
  sortTasks(snapshot.value.tasks.filter((t) => onDay(t, state.day))),
);
let release: UnlistenFn | undefined;
let timer: ReturnType<typeof setInterval> | undefined;
export function errorText(e: unknown) {
  return typeof e === "object" && e && "message" in e
    ? String(e.message)
    : String(e);
}
function accept(value: Snapshot) {
  if (value.revision >= snapshot.value.revision) snapshot.value = value;
}
async function refresh() {
  try {
    accept(await invoke<Snapshot>("snapshot"));
    state.ready = true;
  } catch (e) {
    state.error = errorText(e);
  }
}
async function change(mutation: Mutation) {
  if (state.loading || !state.ready) return false;
  state.loading = true;
  state.error = "";
  try {
    accept(
      await invoke<Snapshot>("mutate", {
        mutation,
        revision: snapshot.value.revision,
      }),
    );
    return true;
  } catch (e) {
    state.error = errorText(e);
    await refresh();
    return false;
  } finally {
    state.loading = false;
  }
}
async function action(
  command: "show_sticky" | "show_main" | "set_pinned" | "quit_app",
  args = {},
) {
  try {
    await invoke(command, args);
    return true;
  } catch (e) {
    state.error = errorText(e);
    return false;
  }
}
function tick() {
  state.day = today();
}
function focus() {
  tick();
  void refresh();
}
async function start() {
  try {
    release = await listen("tasks-changed", () => void refresh());
    await refresh();
    // Show startup errors in the main window too; never substitute demo data.
    await invoke("app_ready");
    timer = setInterval(tick, 1000);
    window.addEventListener("focus", focus);
    document.addEventListener("visibilitychange", focus);
  } catch (e) {
    state.error = errorText(e);
  }
}
function stop() {
  release?.();
  clearInterval(timer);
  window.removeEventListener("focus", focus);
  document.removeEventListener("visibilitychange", focus);
}
export const app = {
  state,
  snapshot: computed(() => snapshot.value),
  todayTasks,
  start,
  stop,
  change,
  action,
  refresh,
};
