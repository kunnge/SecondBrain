import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import router from './router'
import { autoAnimatePlugin } from '@formkit/auto-animate/vue'

// 创建Vue应用实例
const app = createApp(App)

// 使用Pinia
app.use(createPinia())

// 使用路由
app.use(router)

// 使用 auto-animate
app.use(autoAnimatePlugin)

// 挂载应用
app.mount('#app')
