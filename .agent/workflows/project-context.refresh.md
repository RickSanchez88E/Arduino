---
description: 刷新项目上下文 — 重新扫描仓库并更新 current-context.md
---

# /project-context.refresh

刷新 `docs/project-context/current-context.md` 文件，使其反映仓库当前状态。

## 步骤

1. **扫描仓库结构**
   使用 `find_by_name` 和 `list_dir` 工具扫描整个项目目录结构，记录所有源码文件、配置文件和文档。

2. **识别技术栈**
   检查以下文件以确定技术栈:
   - `package.json` → Node.js/JavaScript/TypeScript
   - `requirements.txt` / `pyproject.toml` → Python
   - `go.mod` → Go
   - `Cargo.toml` → Rust
   - `tsconfig.json` → TypeScript
   - `vite.config.*` / `next.config.*` / `webpack.config.*` → 构建工具

3. **识别核心模块**
   根据目录结构识别主要功能模块，记录每个模块的:
   - 职责描述
   - 文件数量
   - 关键文件路径

4. **评估风险区域**
   标记以下高风险区域:
   - 包含复杂业务逻辑的文件
   - 被大量其他文件依赖的文件 (使用 `grep_search` 查找 import 语句)
   - 数据库 schema / 迁移文件
   - 认证和授权相关文件

5. **更新 current-context.md**
   用收集到的信息更新 `docs/project-context/current-context.md`，包括:
   - 技术栈表格
   - 架构边界图
   - 核心模块列表
   - 风险区域表格
   - 约束与惯例
   - 更新时间戳

6. **输出摘要 (中文)**
   向用户输出中文摘要，说明发生了什么变化。

> [!IMPORTANT]
> 此工作流不修改任何源码文件，仅更新文档。
