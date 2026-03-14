---
description: 实施任务 — 按照 spec 和计划执行具体的代码编写任务
---

# /speckit.implement

执行一个具体的编码任务，遵循 spec 和实施计划。

## 前置条件

- 必须指定要实施的任务 (TASK-{SPEC-NNN}-{NN})
- 对应的 spec 和 plan 必须存在
- 任务状态必须为 `📋 待认领` 或 `🔄 进行中`

## 步骤

1. **环境准备**
   - 读取任务文件 `docs/specs/tasks/TASK-{SPEC-NNN}-{NN}.md`
   - 读取关联的 spec 和 plan
   - 读取宪法 `docs/specs/CONSTITUTION.md`
   - 读取项目上下文 `docs/project-context/current-context.md`
   - 检查 `docs/agent-board/agent-registry.md` 确认文件锁

2. **声明文件锁**
   在 `docs/agent-board/agent-registry.md` 中注册:
   - Agent ID
   - 要编辑的文件列表
   - 预期完成时间

3. **更新任务状态**
   将任务状态更新为 `🔄 进行中`。

4. **实施编码**
   按照任务描述进行编码:
   - 严格遵循 spec 中的技术方案
   - 遵循宪法中的所有原则
   - 每次修改不超过 5 个文件
   - 包含必要的测试代码

5. **自检清单**
   完成编码后执行自检:
   - [ ] 代码是否符合 spec 描述？
   - [ ] 是否包含必要的测试？
   - [ ] 是否符合宪法原则？
   - [ ] 是否有硬编码的密钥或敏感信息？
   - [ ] 是否更新了相关文档？
   - [ ] 没有安装未声明的依赖？

6. **运行测试**
   // turbo
   运行相关的测试套件，确保:
   - 新测试通过
   - 既有测试未被破坏

7. **更新状态**
   - 更新任务状态为 `✅ 完成`
   - 释放 `agent-registry.md` 中的文件锁
   - 更新 `current-context.md` (如果架构有变化)

8. **写 Handoff 笔记**
   在 `docs/handoffs/` 中创建交接笔记，使用 `HANDOFF-TEMPLATE.md` 模板。

9. **输出摘要 (中文)**
   向用户呈现中文实施摘要。

> [!CAUTION]
> 禁止修改不在任务声明范围内的文件。
> 禁止安装任务中未声明的依赖。
