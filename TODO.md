# TODO

## 待用户确认

- [ ] GitHub Pages：推送到 `main` 后，在 GitHub Settings → Pages → Source 选择 **GitHub Actions**，再触发或等待 docs workflow。
- [ ] Search Console：等站点部署后，按 `checkpoint.md` 中任务 12 指引获取 Google / Bing verification token，再写入 `docs/.vitepress/verification-meta.mts`。
- [ ] Sitemap：Search Console / Bing Webmaster 验证后提交 `https://zenine.github.io/nudge/sitemap.xml`。

## 后续可选增强

- [ ] 若公开 README 需要以 English 作为默认入口，可在发布前把 `README.en.md` 内容切回 `README.md`，并保留简中为 `README.zh-CN.md`。
- [ ] 为 Nudge 文档站补更深的命令参考页，例如 `doctor`、`daily sync`、`review weekly`、`mcp serve`。
