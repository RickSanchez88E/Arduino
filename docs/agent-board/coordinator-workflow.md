# 多 Agent 协调工作流 (Multi-Agent Coordinator)

> 适用于: AG Workflow Builder 首次功能开发阶段
> 基于: 三层架构 (UI / 逻辑 / 数据)
> Agent 数量: 4 个角色 + 1 个协调者

---

## 一、Agent 拓扑图

```
                    ┌──────────────────────┐
                    │   🎯 Agent-0         │
                    │   协调者 (Coordinator)│
                    │   串行 · 首先启动     │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼───────┐ ┌──────▼───────┐
    │  🖥️ Agent-1    │ │  ⚙️ Agent-2  │ │  💾 Agent-3  │
    │  UI 层         │ │  逻辑层       │ │  数据层       │
    │  (前端界面)     │ │  (工作流引擎) │ │  (持久化)     │
    │  可并行 ←──────►│ │  可并行 ←────►│ │  可并行       │
    └────────────────┘ └──────────────┘ └──────────────┘
                               │
                    ┌──────────▼───────────┐
                    │  🔗 Agent-4          │
                    │  集成层 (Integration) │
                    │  串行 · 最后启动      │
                    └──────────────────────┘
```

---

## 二、执行阶段

### 阶段 0: 协调者准备 (Agent-0)
- 创建/更新 spec 和 plan
- 注册所有 agent 到 agent-registry
- 声明文件所有权和锁
- 输出各 agent 的启动提示词

### 阶段 1: 并行开发 (Agent-1 / Agent-2 / Agent-3)
- 三个 agent 同时工作，各自负责一个架构层
- 通过接口契约文件 (`src/types/` 或 `src/interfaces/`) 对齐
- 接口契约由 Agent-0 在阶段 0 预先创建

### 阶段 2: 集成整合 (Agent-4)
- 连接三层
- 运行全套测试
- 更新文档和项目上下文

---

## 三、协调者工作流

协调者 (Agent-0) 在每轮开发中执行以下步骤:

### 启动前

1. 读取 `docs/specs/CONSTITUTION.md`
2. 读取 `docs/project-context/current-context.md`
3. 读取当前 spec 和 plan
4. 确认所有 agent 的上一次 handoff 笔记

### 任务分配

5. 在 `docs/agent-board/agent-registry.md` 中注册所有 agent:
   ```
   | Agent ID   | 负责范围       | 当前任务 | 状态    | 独占文件                |
   |------------|---------------|---------|---------|------------------------|
   | Agent-1-UI | src/ui/       | TASK-X  | 🔄 活跃 | src/ui/*, src/styles/* |
   | Agent-2-EN | src/engine/   | TASK-Y  | 🔄 活跃 | src/engine/*           |
   | Agent-3-DA | src/data/     | TASK-Z  | 🔄 活跃 | src/data/*             |
   ```

6. 在文件锁定表中声明所有独占文件

7. 创建/更新接口契约文件:
   ```
   src/types/workflow.ts    — 工作流数据结构定义
   src/types/node.ts        — 节点类型定义
   src/types/api.ts         — API 请求/响应类型
   ```

### 收尾

8. 等待所有 agent 完成并提交 handoff
9. 检查每个 agent 的 handoff 笔记
10. 确认无文件冲突
11. 启动 Agent-4 进行集成
12. 更新 `current-context.md`
13. 释放所有文件锁
14. 更新 spec/任务状态

---

## 四、冲突预防

### 共享文件所有权

以下文件类型在多 agent 并行时可能产生冲突。每个文件必须有且仅有一个指定的所有者:

| 共享文件 | 所有者 | 其他 agent 权限 | 原因 |
|----------|--------|---------------|------|
| `package.json` | Agent-0 (协调者) | 只读 (提需求给协调者) | 所有 agent 都可能需要添加依赖 |
| `tsconfig.json` | Agent-0 (协调者) | 只读 | 编译配置影响全局 |
| `src/types/*.ts` | Agent-0 (协调者) | 只读 (消费接口) | 接口契约是并行 agent 之间的桥梁 |
| `.env` / `.env.example` | Agent-0 (协调者) | 只读 | 环境变量影响全局 |
| `README.md` | Agent-0 (协调者) | 禁止 | 项目说明统一管理 |
| `docs/project-context/*` | Agent-0 (协调者) | 禁止 | 上下文统一刷新 |
| `docs/specs/*` | Agent-0 (协调者) | 禁止 | spec 状态统一管理 |
| `docs/agent-board/*` | Agent-0 (协调者) | 只写自己的行 | 注册表自己登记 |

### 禁区规则

每个 agent 除了自己的独占区域外，禁止访问其他 agent 的目录。
