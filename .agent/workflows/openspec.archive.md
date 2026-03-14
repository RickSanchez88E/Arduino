---
description: 归档提案 — 标记完成，记录合并风险和遗留事项
---

# /openspec.archive

提案完成（或放弃）后，归档并留下完整记录。

## 步骤

1. **检查完成情况**
   读取 `docs/openspec/OS-{NNN}-{slug}/tasks.md`:
   - 所有任务是否都已完成 ✅？
   - 是否有遗留任务？

2. **创建归档笔记**
   基于 `docs/openspec/_templates/archive-note.md` 创建:
   ```
   docs/openspec/OS-{NNN}-{slug}/archive-note.md
   ```
   
   必须记录:
   - **最终状态**: 完成 / 部分完成 / 放弃
   - **合并风险**: 这次改动可能影响其他正在进行的工作吗？
   - **遗留事项**: 尚未解决的问题、已知技术债
   - **学到了什么**: 后续类似工作可以参考的经验

3. **更新提案状态**
   更新 `proposal.md` 状态为:
   - `✅ 已完成` — 所有任务完成
   - `⏸️ 部分完成` — 有遗留任务
   - `🗑️ 已放弃` — 决定不做了

4. **更新项目上下文**
   如果改动影响了架构或模块:
   - 由 `/project-context.refresh` 处理
   - 或手动微调 `current-context.md`

5. **输出归档摘要 (中文)**
   说明这次改动最终做了什么、留下了什么。

> [!NOTE]
> 归档不是删除。所有 OpenSpec 文件夹永久保留在 `docs/openspec/` 中，
> 作为项目决策的可追溯记录。
