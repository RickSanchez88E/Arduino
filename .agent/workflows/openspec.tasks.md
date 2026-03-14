---
description: 拆分任务 — 将设计拆为可并行的小任务，支持多 agent 分工
---

# /openspec.tasks

将设计文档拆分为可独立执行的任务。支持多 agent 并行。

## 步骤

1. **读取设计**
   读取 `docs/openspec/OS-{NNN}-{slug}/design.md`。

2. **拆分任务**
   基于 `docs/openspec/_templates/tasks.md` 创建:
   ```
   docs/openspec/OS-{NNN}-{slug}/tasks.md
   ```
   
   每个任务是一个 checklist 条目，包含:
   - 任务名称
   - 负责范围（哪些文件）
   - 完成标准（怎么算做完）
   - 可选: 分配给哪个 agent

3. **声明文件所有权**
   在 `tasks.md` 中明确列出每个任务触碰的文件。
   如果多个任务触碰同一文件 → 标记为「⚠️ 共享文件」并建议串行执行。

4. **更新 Agent 看板**
   如果涉及多 agent，更新 `docs/agent-board/agent-registry.md`:
   - 注册每个任务的负责 agent
   - 声明文件锁

5. **更新提案状态**
   更新 `proposal.md` 状态为 `📋 已拆分`。

6. **输出任务清单 (中文)**

> [!NOTE]
> 简单的提案可能只有 1-2 个任务，不需要分配多个 agent。
> 任务粒度以「一个 agent 会话能完成」为准。
