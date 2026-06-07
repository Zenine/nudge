import { defineConfig } from 'vitepress'
import { verificationHead } from './verification-meta.mts'

const SITE_URL = 'https://zenine.github.io/nudge'
const PROJECT_NAME = 'Nudge'
const DESCRIPTION = 'Local-first macOS CLI runtime for turning plans into Apple Calendar, Reminders, Notes, and Clock actions.'
const GITHUB_URL = 'https://github.com/Zenine/nudge'
const LICENSE = 'AGPL-3.0-only'

const seoHead = [
  ['meta', { property: 'og:type', content: 'website' }],
  ['meta', { property: 'og:title', content: PROJECT_NAME }],
  ['meta', { property: 'og:description', content: DESCRIPTION }],
  ['meta', { property: 'og:url', content: SITE_URL }],
  ['meta', { property: 'og:image', content: `${SITE_URL}/og.png` }],
  ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
  ['meta', { name: 'twitter:title', content: PROJECT_NAME }],
  ['meta', { name: 'twitter:description', content: DESCRIPTION }],
  ['meta', { name: 'twitter:image', content: `${SITE_URL}/og.png` }],
  ['link', { rel: 'canonical', href: SITE_URL }],
  ['link', { rel: 'alternate', type: 'text/plain', href: `${SITE_URL}/llms.txt` }],
  ['script', { type: 'application/ld+json' }, JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'SoftwareSourceCode',
    name: PROJECT_NAME,
    description: DESCRIPTION,
    url: SITE_URL,
    codeRepository: GITHUB_URL,
    license: LICENSE,
    programmingLanguage: 'Python',
    operatingSystem: 'macOS',
    applicationCategory: 'DeveloperApplication',
  })],
]

export default defineConfig({
  base: '/nudge/',
  title: PROJECT_NAME,
  titleTemplate: `:title | ${PROJECT_NAME}`,
  description: DESCRIPTION,

  head: [
    ['link', { rel: 'icon', href: '/nudge/hero.svg', type: 'image/svg+xml' }],
    ...verificationHead,
    ...seoHead,
  ],

  markdown: {
    config: (md) => {
      md.core.ruler.push('escape_vue_interpolation', (state) => {
        for (const token of state.tokens) {
          if (token.type === 'inline' && token.children) {
            for (const child of token.children) {
              if (child.type === 'text' || child.type === 'html_inline') {
                child.content = child.content
                  .replace(/\{\{/g, '&#123;&#123;')
                  .replace(/\}\}/g, '&#125;&#125;')
              }
            }
          }
        }
      })
    },
  },

  ignoreDeadLinks: true,

  vite: {
    resolve: { preserveSymlinks: true },
    server: { fs: { strict: false } },
  },

  sitemap: {
    hostname: SITE_URL,
    transformItems(items) {
      return items.map((item) => ({
        ...item,
        changefreq: item.url === '' ? 'weekly' : 'monthly',
        priority: item.url === '' ? 1.0 : 0.7,
      }))
    },
  },

  locales: {
    root: {
      label: '简体中文',
      lang: 'zh-CN',
      themeConfig: {
        nav: [
          { text: '快速开始', link: '/quick-start' },
          { text: '命令参考', link: '/reference' },
          { text: 'FAQ', link: '/faq' },
          { text: 'GitHub', link: GITHUB_URL },
        ],
        sidebar: {
          '/': [
            {
              text: '指南',
              items: [
                { text: '快速开始', link: '/quick-start' },
                { text: '命令参考', link: '/reference' },
                { text: 'FAQ', link: '/faq' },
              ],
            },
          ],
        },
      },
    },
    en: {
      label: 'English',
      lang: 'en-US',
      themeConfig: {
        nav: [
          { text: 'Quick Start', link: '/en/quick-start' },
          { text: 'Reference', link: '/en/reference' },
          { text: 'FAQ', link: '/en/faq' },
          { text: 'GitHub', link: GITHUB_URL },
        ],
        sidebar: {
          '/en/': [
            {
              text: 'Guide',
              items: [
                { text: 'Quick Start', link: '/en/quick-start' },
                { text: 'Reference', link: '/en/reference' },
                { text: 'FAQ', link: '/en/faq' },
              ],
            },
          ],
        },
      },
    },
    ja: {
      label: '日本語',
      lang: 'ja',
      themeConfig: {
        nav: [
          { text: 'Quick Start', link: '/ja/quick-start' },
          { text: 'Reference', link: '/ja/reference' },
          { text: 'FAQ', link: '/ja/faq' },
          { text: 'GitHub', link: GITHUB_URL },
        ],
        sidebar: {
          '/ja/': [
            {
              text: 'ガイド',
              items: [
                { text: 'Quick Start', link: '/ja/quick-start' },
                { text: 'Reference', link: '/ja/reference' },
                { text: 'FAQ', link: '/ja/faq' },
              ],
            },
          ],
        },
      },
    },
    'zh-TW': {
      label: '繁體中文',
      lang: 'zh-TW',
      themeConfig: {
        nav: [
          { text: '快速開始', link: '/zh-TW/quick-start' },
          { text: '命令參考', link: '/zh-TW/reference' },
          { text: 'FAQ', link: '/zh-TW/faq' },
          { text: 'GitHub', link: GITHUB_URL },
        ],
        sidebar: {
          '/zh-TW/': [
            {
              text: '指南',
              items: [
                { text: '快速開始', link: '/zh-TW/quick-start' },
                { text: '命令參考', link: '/zh-TW/reference' },
                { text: 'FAQ', link: '/zh-TW/faq' },
              ],
            },
          ],
        },
      },
    },
  },

  themeConfig: {
    logo: '/hero.svg',
    socialLinks: [
      { icon: 'github', link: GITHUB_URL },
    ],
    search: { provider: 'local' },
    footer: {
      message: 'Built with <a href="https://github.com/lordmos/meridian" target="_blank">Meridian</a>',
    },
  },
})
