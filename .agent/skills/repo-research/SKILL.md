---
name: repo-research
description: 扫描仓库结构、识别核心模块、更新项目上下文文档
---

# Repo Research Skill

此技能用于深度扫描仓库，识别核心模块、约束和惯例，并更新 `docs/project-context/current-context.md`。

## 使用场景

- 项目初始化后首次上下文建立
- 新成员（人或 agent）加入时了解项目
- 定期上下文刷新（配合 `/project-context.refresh` 工作流）
- 重大架构变更后

## 执行步骤

### 第一步: 文件系统扫描

扫描整个项目目录，收集以下信息:

```
1. 使用 list_dir 获取顶层目录结构
2. 使用 find_by_name 按文件类型分类:
   - 源码文件: *.ts, *.tsx, *.js, *.jsx, *.py, *.go, *.rs, *.java
   - 配置文件: package.json, tsconfig.json, .env*, vite.config.*, next.config.*
   - 测试文件: *.test.*, *.spec.*, __tests__/*
   - 文档文件: *.md, *.mdx
   - 样式文件: *.css, *.scss, *.less
3. 统计每种类型的文件数量
4. 记录目录深度和结构模式
```

### 第二步: 技术栈识别

检查标志性配置文件:

| 文件 | 推断 |
|------|------|
| `package.json` | Node.js 生态; 检查 dependencies 确定框架 |
| `tsconfig.json` | TypeScript 项目 |
| `vite.config.*` | Vite 构建 |
| `next.config.*` | Next.js 框架 |
| `webpack.config.*` | Webpack 构建 |
| `tailwind.config.*` | Tailwind CSS |
| `prisma/schema.prisma` | Prisma ORM |
| `docker-compose.yml` | Docker 容器化 |
| `requirements.txt` | Python 项目 |
| `pyproject.toml` | 现代 Python 项目 |
| `go.mod` | Go 项目 |
| `Cargo.toml` | Rust 项目 |

### 第三步: 核心模块识别

对于每个顶层目录或主要子目录:

```
1. 统计文件数量
2. 阅读关键文件（index.*, main.*, app.*）的前 50 行
3. 使用 grep_search 查找 export/import 关系
4. 确定模块的:
   - 名称
   - 职责描述
   - 入口文件
   - 关键依赖
   - 估计大小（文件数/行数）
```

### 第四步: 依赖关系分析

```
1. 使用 grep_search 查找 import/require 语句
2. 建立模块间的依赖图
3. 识别高扇入文件（被大量导入的文件 = 变更风险高）
4. 识别高扇出文件（导入大量模块的文件 = 复杂度高）
```

### 第五步: 约束和惯例提取

检查以下来源以提取隐式约束:

```
1. .eslintrc / .prettierrc → 代码风格约束
2. .gitignore → 排除规则
3. CI/CD 配置 → 构建和部署约束
4. README.md → 项目约定说明
5. CONTRIBUTING.md → 贡献指南
6. docs/specs/CONSTITUTION.md → 项目宪法
```

### 第六步: 输出更新

将收集到的所有信息写入 `docs/project-context/current-context.md`:

必须包含的章节:
- 项目概况
- 技术栈表格
- 架构边界图 (ASCII 或 Mermaid)
- 核心模块列表（含职责和关键文件）
- 自主编辑风险区域
- 约束与惯例
- 更新日志

### 第七步: 摘要生成

生成中文摘要，包含:
- 仓库概况（X 个文件，Y 个目录）
- 技术栈总结
- 核心模块总结
- 发现的关键风险
- 建议的下一步操作

## 输出格式

所有输出必须为中文，遵循 `current-context.md` 的既有格式。

## 注意事项

- 此技能 **不修改任何源码文件**
- 仅更新 `docs/project-context/current-context.md`
- 如果 `current-context.md` 不存在，则创建它
- 如果已存在，保留更新日志并追加新条目
