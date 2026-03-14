---
description: 执行变更 — 按任务清单编码，完成后记录结果
---

# /openspec.apply

执行具体的编码工作，并记录结果。

## 步骤

1. **读取上下文**
   - 读取 `docs/openspec/OS-{NNN}-{slug}/tasks.md` 确认要做哪个任务
   - 读取 `docs/openspec/OS-{NNN}-{slug}/design.md` 了解做法
   - 读取 `docs/specs/CONSTITUTION.md` 确认约束
   - 检查 `docs/agent-board/agent-registry.md` 确认无文件冲突

2. **声明工作范围**
   在 `agent-registry.md` 中注册:
   - 当前 Agent 标识
   - 要编辑的文件列表
   - 关联的 OpenSpec 编号

3. **编码实施**
   按照设计和任务清单编码:
   - 一次只做一个任务
   - 严格只改任务声明的文件
   - 完成后在 `tasks.md` 中打勾 ✅

4. **写 review 记录**
   基于 `docs/openspec/_templates/review.md` 创建:
   ```
   docs/openspec/OS-{NNN}-{slug}/review.md
   ```
   记录:
   - 实际改了什么（和设计有无偏差）
   - 测试情况
   - 遗留问题

5. **释放文件锁**
   在 `agent-registry.md` 中释放文件锁。

6. **输出完成摘要 (中文)**

> [!IMPORTANT]
> 如果实施过程中发现设计有误，**不要继续**。
> 回到 `/openspec.design` 更新设计文档后再施工。
