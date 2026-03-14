# 任务清单: OS-001 - ArUco 视觉定位导航

## 任务列表

- [ ] **任务 1: 创建摄像头驱动与 OpenCV ArUco 基础识别**
  - 范围: `smart_car_project/.../wireless_controller/aruco_tracker.py`
  - 完成标准: 能够使用 `cv2.VideoCapture(0)` 或类似方式打开 PC 上的视频流。设置正确的 ArUco 字典（如 `DICT_4X4_50`），在获取到的 `Bgr` 图像帧上检测指定的 Marker IDs，然后用 `cv2.aruco.drawDetectedMarkers` 绘制边框和 ID，实现在屏幕上实时预览视频流并识别出画面中出现的所有二维码。
  - 负责: Agent-1 (UI/CV层)

- [ ] **任务 2: 计算透视变换与 2D 坐标映射**
  - 范围: `smart_car_project/.../wireless_controller/aruco_tracker.py`
  - 完成标准: 指定 4 个用作锚点的 Marker（如 ID: 0, 1, 2, 3，放在场地的矩形四个角上），获取这四者的中心点像素作为源点集 `src_pts`。预置现实世界的目标宽高速率坐标作为目的点集 `dst_pts` （如 `(0,0)`, `(1.0, 0)`, `(1.0, 1.0)`, `(0, 1.0)` 表示 1m x 1m）。使用 `cv2.getPerspectiveTransform` 得到 Homography 矩阵。当场地里出现了小车自己的 Marker 时（如 ID 10），使用 `cv2.perspectiveTransform` 计算出其真实世界的 $(x, y)$ 并打印出来。
  - 负责: Agent-1 (UI/CV层)

- [ ] **任务 3: 解析并计算小车航向角 (θ)，防抖滤波**
  - 范围: `smart_car_project/.../wireless_controller/aruco_tracker.py`
  - 完成标准: 小车 Marker 上能够提取四个角的排列顺序（TL, TR, BR, BL），经过相同的透视变换后，使用前方两点的中点与后方两点的中点组成的有向向量计算 $\arctan$ 来得出小车在绝对重构坐标系下的全局朝向偏移角度 $\theta$。设计平滑滤波器或异常丢弃逻辑平滑这些定位数据，包装为可以供外部轮询调用的接口。
  - 负责: Agent-2 (逻辑层)

- [ ] **任务 4: 测试集成入现有控制台程序雏形**
  - 范围: `smart_car_project/.../wireless_controller/car_control.py` 与 `aruco_tracker.py`
  - 完成标准: 独立编写一个可以在多线程环境下（`threading.Thread` 等）工作不断获取最新 $(x, y, \theta)$ 的消费者实例并输出以确保它不用阻塞就可以向原有的主控 Python Tkinter 代码发送数据或取代内部的坐标显示，确保整合无冲突。
  - 负责: Agent-4 (集成层)

## 文件所有权

| 文件路径 | 归属任务 | 备注 |
|----------|---------|------|
| `*/wireless_controller/aruco_tracker.py` | 任务 1,2,3 | OpenCV 独立测试，不冲突 |
| `*/wireless_controller/car_control.py` | 任务 4 | ⚠️ 共享 (集成)，需要与正在运行的 UI/Socket 通信集成 |

## 执行顺序

建议的执行顺序或并行分组:
1. 先做: 任务 1（打开摄像头能看到自己标出来的框）
2. 再做: 任务 2（标定二维坐标位置系）
3. 再做: 任务 3（角度计算加防抖封装）
4. 最后串行: 任务 4（并入现有通信大逻辑中）
