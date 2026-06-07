import type { HeadConfig } from 'vitepress'

// Fill these values after Google Search Console / Bing Webmaster Tools return
// their verification tokens. Do not store account credentials or API keys here.
const GOOGLE_SITE_VERIFICATION = ''
const BING_SITE_VERIFICATION = ''

export const verificationHead: HeadConfig[] = [
  ...(GOOGLE_SITE_VERIFICATION
    ? [['meta', { name: 'google-site-verification', content: GOOGLE_SITE_VERIFICATION }]] as HeadConfig[]
    : []),
  ...(BING_SITE_VERIFICATION
    ? [['meta', { name: 'msvalidate.01', content: BING_SITE_VERIFICATION }]] as HeadConfig[]
    : []),
]
