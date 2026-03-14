---
description: 查看和审查项目宪法 — 显示当前生效的核心原则和治理规则
---

# /speckit.constitution

查看和管理项目宪法 (`docs/specs/CONSTITUTION.md`)。

## 步骤

1. **读取宪法**
   使用 `view_file` 读取 `docs/specs/CONSTITUTION.md`。

2. **验证完整性**
   确认宪法包含以下必要章节:
   - [ ] 架构一致性原则
   - [ ] 测试要求原则
   - [ ] 重构审批原则
   - [ ] 性能边界原则
   - [ ] 安全约束原则
   - [ ] 文档更新原则
   - [ ] 规范驱动开发原则

3. **展示给用户**
   以结构化方式向用户展示当前宪法内容。

4. **处理修改请求**
   如果用户要求修改宪法:
   - 记录修改理由
   - 更新 `CONSTITUTION.md`
   - 在 `docs/decisions/` 中创建对应的 ADR
   - 更新修订历史

> [!WARNING]
> 修改宪法是高影响操作。每次修改都必须在 ADR 中记录原因。
