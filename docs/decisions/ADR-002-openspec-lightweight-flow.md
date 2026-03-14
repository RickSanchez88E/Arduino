# ADR-002: 引入 OpenSpec 轻量规范流程

> 状态: ✅ 已采纳
> 日期: 2026-03-13
> 决策者: Workflow Design Agent (经用户授权)

## 背景

现有的 Spec Kit 流程 (`/speckit.*`) 提供了完整的规范驱动开发能力，但对于以下场景过于厚重:
- Bug 修复
- 小功能迭代
- 配置/工具链调整
- 探索性原型
- 棕地 (brownfield) 代码改进

需要一个更轻量的并行流程，让小改动不必承受全套 spec 审批流程的开销。

## 决策

引入 **OpenSpec** 轻量规范流程，与 Spec Kit 并行共存:

```
OpenSpec (轻量):  propose → [clarify] → design → tasks → apply → archive
Spec Kit (正式):  specify → plan → tasks → implement → handoff
```

两者的路由规则:
| 情况 | 使用流程 |
|------|---------|
| 全新功能，跨多模块 | Spec Kit |
| 架构级变更 | Spec Kit |
| Bug 修复、小迭代 | OpenSpec |
| 配置/工具链调整 | OpenSpec |
| 探索性原型 | OpenSpec |
| 高风险区域改动 | 由 OpenSpec 自动建议升级到 Spec Kit |

## 核心区别

| 维度 | OpenSpec | Spec Kit |
|------|---------|----------|
| 审批门 | 无硬性审批 | 必须审批 |
| 文档量 | 1-3 段话 | 完整模板 |
| 阶段跳过 | 可以跳过 clarify | 不可跳过 |
| 归档 | 必选（含合并风险） | 通过 handoff |
| 适用场景 | 棕地迭代 | 绿地功能 |

## 理由

1. **降低摩擦**: 不让流程成为小改动的阻碍
2. **保持追溯**: 即使是小改动也有 proposal → archive 的记录链
3. **风险管控**: 自动检测高风险区域并建议升级流程
4. **共存共荣**: 不替换 Spec Kit，而是提供另一条赛道

## 影响

- 规则需要更新: 原「先 Spec 后代码」调整为「先 Spec 或 Proposal 后代码」
- 宪法原则 7 需要补充对 OpenSpec 的认可
- 新增 `docs/openspec/` 目录和模板

## 替代方案

1. 只用 Spec Kit + 简化模板 → 拒绝: 流程结构仍然厚重
2. 不设流程直接编码 → 拒绝: 缺乏追溯性
3. 使用外部工具 (Jira, Linear) → 拒绝: 增加工具切换成本
