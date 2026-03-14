# 智能小车自主导航系统 (Smart Car Navigation System)

> 最后更新: 2026-03-14
> 状态: 🟢 初始化 (Active)

## 项目概况 (Project Overview)

| 属性 | 值 |
|------|------|
| **项目名称** | 基于视觉与编码器的智能小车自主导航系统 |
| **项目类型** | 软硬件结合 (硬件控制 + 上位机视觉导航) |
| **当前状态** | 基础运动控制与上位机通信已实现，待整合视觉定位 |
| **技术栈** | C++ (Arduino), Python (PC 上位机) |
| **应用类型** | 自动引导车 (AGV) 室内导航 |
| **仓库路径** | `d:\Users\rick\Downloads\Arduino` |

## 技术栈 (Tech Stack)

| 层次 | 技术 | 状态 |
|------|------|------|
| 硬件主控 | Arduino Uno (Elegoo Smart Robot Car V4.0) | ✅ |
| 底层语言 | C++ / Arduino dialect | ✅ |
| 传感器 | 电机编码器, HC-SR04(超声波), ADXL345(加速度计), HMC5883L(磁力计) | ✅ |
| 通信协议 | 基于 Socket 的 TCP 通信 (IP: 192.168.4.1:100), 自定义 JSON-like 帧 | ✅ |
| 上位机语言 | Python 3 | ✅ |
| 上位机 UI | Tkinter | ✅ |
| 视觉定位 | OpenCV + ArUco Marker (Top-down camera) | ⚠️ 待实现 |
| 路径规划 | 人工势场法 (APF) 或简化点到点直线导航 | ⚠️ 待实现 |

## 架构边界 (Architectural Boundaries)

```mermaid
graph TD
    subgraph PC_上位机 [上位机控制端 (Python)]
        UI[Tkinter 地面控制站 UI]
        CV[OpenCV & ArUco 定位系统]
        TCP_Client[TCP Socket 客户端]
        
        UI <--> TCP_Client
        CV --> UI
    end

    subgraph Arduino_下位机 [小车主控端 (Arduino)]
        TCP_Server[TCP/Serial 桥接 (ESP8266)]
        Parser[命令解析与状态发射]
        PID_Pos[外环: 位置 PID]
        PID_Yaw[中环: 航向 PID]
        PID_Vel[内环: 速度 PID]
        Motors[四轮差速电机]
        Sensors[IMU, 编码器]
        
        TCP_Server <--> Parser
        Parser --> PID_Pos
        PID_Pos --> PID_Yaw
        PID_Yaw --> PID_Vel
        PID_Vel --> Motors
        Sensors --> PID_Pos
        Sensors --> PID_Yaw
        Sensors --> PID_Vel
        Sensors --> Parser
    end

    TCP_Client <==>|"{GOAL:...}, {T:...}"| TCP_Server
```

## 核心模块 (Core Modules)

### 1. Arduino 底层控制 (`smart_car_project.ino`)
- **职责**: 接收上位机坐标，通过级联 PID 算法驱动小车移动到目标。
- **文件**: `smart_car_project/smart_car_project-main/smart_car_project-main/smart_car_project.ino`
- **主要逻辑**:
  - 位置 PID -> 基础速度
  - 航向 PID (基于磁力计姿态融合) -> 差速补偿
  - 速度 PID -> 编码器反馈转 PWM
- **里程计 (Odometry)**: 融合编码器和 IMU 计算局部相对位置与航向。

### 2. Python 地面控制站 (`car_control.py`)
- **职责**: 监控小车状态，下发目标点，可视化运行轨迹。
- **文件**: `smart_car_project/smart_car_project-main/smart_car_project-main/wireless_controller/car_control.py`
- **主要逻辑**:
  - `RobotGCS`: 基于 Tkinter 的 GUI。
  - TCP Socket 连接 (`192.168.4.1:100`) 收发指令。
  - 画布 (Canvas) 实时绘制小车相对位置和航向追踪。

### 3. [待规划] 视觉定位与导航算法
- **职责**: 通过俯视摄像头识别现场分布的 ArUco Tag 和小车顶部的 Tag，计算全局真实坐标 (x, y, θ)。
- **需求参考**: `项目要求.txt`

## 评估风险区域 (Risky Areas)

| 风险等级 | 区域 | 文件 | 原因 |
|----------|------|------|------|
| 🔴 高 | 视觉坐标与里程计融合 | N/A | 目前 Arduino 依赖自身编码器里程计（存在机械误差），后续需融入顶视相机全局坐标，坐标系的标定和融合 (PC 发送纠偏还是直接覆盖) 是难点。 |
| 🔴 高 | 硬件串行与中断竞争 | `smart_car_project.ino` | 编码器使用引脚中断 (PCINT)，过高频可能导致主循环或网络解析丢包。 |
| 🟡 中 | 无线通信质量 | `car_control.py` / `ino` | 使用简单的字符串协议 `"{T:...}"`，若发生断连重连可能导致指令状态不同步。 |
| 🟡 中 | 阻塞式 UI 更新 | `car_control.py` | Tkinter 的 `after` 虽然能更新，但 socket 接收如果异常可能挂起，目前是放到了守护线程中处理。 |

## 约束与惯例 (Constraints & Conventions)

1. **先规范后代码** — 大功能用 `/speckit.specify`，小改动用 `/openspec.propose`
2. **读宪法** — 开始前读 `docs/specs/CONSTITUTION.md`
3. **窄范围** — 只改任务声明内文件
4. **共享文件声明** — 编辑前在 `agent-registry.md` 声明
5. **交接笔记** — 会话结束前执行 `/handoff`
