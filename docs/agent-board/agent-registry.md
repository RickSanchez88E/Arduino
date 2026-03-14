# Agent 注册表 (Agent Registry)

> 最后更新: 2026-03-13

## 活跃 Agent (Active Agents)

| Agent ID | 负责范围 | 当前任务 | 状态 | 独占文件 |
|----------|---------|---------|------|---------|
| Agent-1 | UI/CV 层 | OS-001/Task 1-2 | 运行中 | `aruco_tracker.py` |

## 文件锁定表 (File Lock Table)

| 文件路径 | 锁定 Agent | 锁定时间 | 预期释放时间 |
|----------|-----------|---------|-------------|
| `smart_car_project/smart_car_project-main/smart_car_project-main/wireless_controller/aruco_tracker.py` | Agent-1 | 2026-03-14 | — |

## 冲突记录 (Conflict Log)

| 日期 | Agent A | Agent B | 冲突文件 | 解决方式 |
|------|---------|---------|---------|---------|
| — | — | — | — | — |

## 规则

1. 同一文件同一时间只能由一个 agent 编辑
2. 编辑共享文件前必须在此注册表中声明
3. 会话结束前必须释放所有文件锁
4. 冲突发生时以先声明者优先
