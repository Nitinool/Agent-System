import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import Home from './views/Home.vue'
import './style.css'
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Home },
    { path: '/tasks', component: () => import('./views/Tasks.vue') },
    { path: '/projects', component: () => import('./views/Projects.vue') },
    { path: '/records', component: () => import('./views/Records.vue') },
    { path: '/jobs', component: () => import('./views/Jobs.vue') },
    { path: '/finance', component: () => import('./views/Finance.vue') },
  ],
})
createApp(App).use(createPinia()).use(router).mount('#app')
