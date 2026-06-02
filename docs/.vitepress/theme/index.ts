import DefaultTheme from 'vitepress/theme'
import { startInlineIconsWatcher } from './inline-svg'
import './style.css'

export default {
  extends: DefaultTheme,
  enhanceApp() {
    if (typeof window !== 'undefined') {
      window.requestAnimationFrame(() => startInlineIconsWatcher())
    }
  },
}
