#### 💻 变更类型 | Change Type

- [x] ✨ feat
- [ ] 🐛 fix
- [ ] ♻️ refactor
- [ ] 💄 style
- [ ] 🔨 chore
- [ ] 📝 docs

#### 🔀 变更说明 | Description of Change

Adds the SteadyRouter icon ({{site_url}}), for the LobeHub provider PR. Mono and Avatar variants, drawn with `currentColor` from the brand's own logo. No wordmark variant yet, so no Text or Combine. The id mapping and the icon are in the React Native package too.

#### 📝 补充信息 | Additional Information

Written with AI assistance (Claude Code). No human code review yet. `tsc --noEmit` passes at the root and in `packages/react-native`. `lobedocs build`: the client and server bundles build, including this page; its prerender step then failed here with a connection refused from its own local server, inside a docker container, so the full build was not seen to finish. In a local docs build the icon is in the list, and its Icons and Avatars pages render.
