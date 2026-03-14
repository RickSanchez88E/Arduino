# 抖音视频下载器 — Antigravity 规则 (Rules)

## 规范驱动开发规则

### 规则 1: 先规范后代码 (Spec / Proposal Before Code)
所有功能开发必须先创建规范文档:
- 大功能/架构变更 → 使用 `/speckit.specify` 创建 spec，经批准后编码
- 小改动/bug修复/迭代 → 使用 `/openspec.propose` 创建 proposal，无需硬性审批

无论哪条路径，都禁止直接编码。

### 规则 2: 宪法遵从 (Constitution Compliance)
所有 agent 在开始工作前必须读取并遵守 `docs/specs/CONSTITUTION.md` 中的原则。

### 规则 3: 上下文感知 (Context Awareness)
开始任何编码工作前，必须先读取:
- `docs/project-context/current-context.md` — 了解当前项目状态
- `docs/specs/CONSTITUTION.md` — 了解不可违反原则
- `docs/agent-board/agent-registry.md` — 了解当前活跃的 agent 和文件锁

## 多 Agent 冲突控制规则

### 规则 4: 窄范围所有权 (Narrow Scope Ownership)
每个 agent 只能在其声明的任务范围内工作。禁止修改超出任务声明的文件。

### 规则 5: 共享文件声明 (Shared File Declaration)
编辑任何共享文件前，必须先在 `docs/agent-board/agent-registry.md` 的文件锁定表中声明。
共享文件包括但不限于:
- 配置文件 (package.json, tsconfig.json, etc.)
- 路由定义文件
- 全局状态管理文件
- 共用工具函数文件
- 数据库 schema 文件

### 规则 6: 强制交接 (Mandatory Handoff)
每个 agent 在结束工作前必须:
1. 在 `docs/handoffs/` 中创建交接笔记
2. 释放 agent-registry 中的所有文件锁
3. 更新关联任务的状态

### 规则 7: 中文摘要 (Chinese Summaries)
所有面向用户的摘要和报告必须使用中文。
包括但不限于:
- 会话结束摘要
- 分析报告
- 错误报告
- 状态更新
- 交接笔记中的关键信息

## 安全规则

### 规则 8: 依赖安全 (Dependency Safety)
不得安装未在 spec 或任务中明确声明的依赖。
安装任何新依赖前必须:
1. 说明理由
2. 检查已知漏洞
3. 获得用户确认

### 规则 9: 无业务逻辑修改 (No Business Logic Modification)
在 scaffold/setup 阶段，禁止修改任何已有的业务逻辑代码。
此规则在项目进入正式开发阶段后由具体的 spec 覆盖。

## OpenSpec 流程规则

### 规则 10: 流程路由 (Flow Routing)
根据变更范围选择正确的流程:
- **Spec Kit** (`/speckit.*`): 全新功能、架构变更、跨 3+ 模块的改动
- **OpenSpec** (`/openspec.*`): Bug 修复、模块内迭代、配置调整、原型探索

当 OpenSpec 提案触碰高风险区域时，agent 必须建议用户升级到 Spec Kit 流程。
两种流程共享同一套冲突控制规则（规则 4-6）和安全规则（规则 8-9）。
