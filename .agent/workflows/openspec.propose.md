---
description: 快速提案 — 用一段话描述想做的变更，生成轻量 proposal 文件
---

# /openspec.propose

用最小开销提出一个变更提案。适用于 bug 修复、小功能、重构片段、探索性改动等。

## 何时用 OpenSpec 而非 Spec Kit

| 情况 | 使用 |
|------|------|
| 全新功能（跨多模块） | `/speckit.specify` |
| 架构级变更 | `/speckit.specify` |
| Bug 修复 / 小改动 | ✅ `/openspec.propose` |
| 已有模块内迭代 | ✅ `/openspec.propose` |
| 探索性原型 | ✅ `/openspec.propose` |
| 配置/工具链调整 | ✅ `/openspec.propose` |

## 步骤

1. **一句话描述**
   向用户索要一段话描述，回答三个问题:
   - **做什么** (What)
   - **为什么** (Why)
   - **改哪里** (Where)

2. **生成提案编号**
   扫描 `docs/openspec/` 目录，确定下一个编号:
   ```
   OS-001, OS-002, OS-003, ...
   ```

3. **创建提案文件**
   基于 `docs/openspec/_templates/proposal.md` 创建:
   ```
   docs/openspec/OS-{NNN}-{slug}/proposal.md
   ```
   - 自动填入: 编号、日期、描述
   - 状态设为 `💡 提议中`
   - 列出初步影响文件（可以是 agent 推断 + 用户补充）

4. **快速风险扫描**
   检查提案是否触碰高风险区域:
   - 查阅 `docs/project-context/current-context.md` 中的风险区域表
   - 如果触碰 🔴 高风险 → 建议升级到 Spec Kit 流程
   - 如果仅 🟢/🟡 → 继续 OpenSpec 流程

5. **输出提案摘要 (中文)**
   一段话总结提案内容，等待用户确认或补充。

> [!TIP]
> 提案无需批准即可继续到 `/openspec.clarify` 或直接到 `/openspec.design`。
> 这是 OpenSpec 和 Spec Kit 的核心区别: **没有硬性审批门**。
