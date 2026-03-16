# Smart Car Autonomous Navigation System

An Arduino-based autonomous robot car with cascaded PID control, wireless ground control station, and ArUco marker-based visual localization.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  Ground Control Station               │
│  (Python/Tkinter on Mac)                             │
│  ┌────────────┐  ┌──────────┐  ┌─────────────────┐  │
│  │ car_control│  │  ArUco   │  │ iPhone Camera   │  │
│  │   (GCS)    │←─│ Tracker  │←─│  (HTTPS Stream) │  │
│  └─────┬──────┘  └──────────┘  └─────────────────┘  │
│        │ WiFi / Serial                               │
└────────┼─────────────────────────────────────────────┘
         ▼
┌──────────────────────────────────────────────────────┐
│            Elegoo Smart Robot Car V4.0                │
│  ┌────────────────────────────────────────────────┐  │
│  │         smart_car_project.ino                  │  │
│  │  Cascaded PID: Position → Heading → Velocity  │  │
│  │  Sensors: Encoder + Magnetometer + Accel      │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

## Project Structure

```
smart_car_project/
├── smart_car_project.ino      # Arduino firmware (cascaded PID control)
└── wireless_controller/
    ├── car_control.py         # Ground Control Station (Tkinter GUI)
    ├── aruco_tracker.py       # ArUco vision localization system
    ├── iphone_camera.py       # iPhone → Mac wireless camera (HTTPS)
    ├── test_camera.py         # Camera & ArUco detection test tool
    └── aruco_markers/         # Pre-generated ArUco marker images
        ├── aruco_marker_0.png
        ├── aruco_marker_1.png
        ├── aruco_marker_2.png
        ├── aruco_marker_3.png
        └── aruco_marker_10.png
```

## Components

### 1. Arduino Firmware (`smart_car_project.ino`)

Three-tier cascaded PID control system:

| Layer | Controller | Input | Output | Sensor |
|-------|-----------|-------|--------|--------|
| Outer | Position PID | Target distance (m) | Target velocity (m/s) | Wheel encoders |
| Middle | Heading PID | Target angle (rad) | Differential correction | Magnetometer (HMC5883) |
| Inner | Velocity PID | Target wheel speed (m/s) | PWM duty cycle | Wheel encoders |

**Key features:**
- Feed-forward + PID for fast response
- EMA-filtered magnetometer readings
- Anti-windup on integral terms
- Serial telemetry protocol: `{T:posX,posY,theta,...}`
- Command protocol: `{GOAL:x,y}`, `{ZERO}`, `{SPIN}`

### 2. Ground Control Station (`car_control.py`)

Python/Tkinter desktop application for real-time robot monitoring and control.

- Live compass display with heading needle
- 2D position map with trajectory trail
- Telemetry readout (position, velocity, heading error)
- Goal setting via coordinate input
- Magnetometer spin calibration
- WiFi/Serial connection management

### 3. ArUco Vision Localization (`aruco_tracker.py`)

Top-down camera system using ArUco markers for indoor robot localization.

- **4 anchor markers** (ID 0-3) define the world coordinate frame
- **1 robot marker** (ID 10) tracks the car's position and heading
- Homography-based pixel → metric coordinate transform
- EMA-smoothed pose output: `(x, y, theta)`
- Persistent calibration (saved to JSON)
- Lost-marker fallback with configurable timeout
- Thread-safe design for real-time integration

### 4. iPhone Camera Stream (`iphone_camera.py`)

Wireless camera solution using iPhone Safari as the video source — no app installation required.

- Mac hosts HTTPS server with self-signed certificate
- iPhone Safari streams camera frames via HTTP POST
- Detection results displayed on **both** iPhone and Mac
- Supports rear camera at up to 1920×1080

### 5. Camera Test Tool (`test_camera.py`)

Standalone utility for testing camera input and ArUco detection.

- Auto-scans available cameras (MacBook + Continuity Camera)
- Camera preview with selection
- Real-time ArUco detection with pose overlay
- Supports direct camera ID, URL, and scan-only modes

## Quick Start

### Prerequisites

```bash
pip install opencv-python opencv-contrib-python numpy
```

### Test ArUco Detection

```bash
# Using MacBook camera
python wireless_controller/test_camera.py

# Using iPhone as camera
python wireless_controller/iphone_camera.py
# Then open the displayed URL on iPhone Safari
```

### Run Ground Control Station

```bash
python wireless_controller/car_control.py
```

### Generate ArUco Markers

```bash
python wireless_controller/aruco_tracker.py --generate
```

Print markers ID 0-3 at arena corners, attach ID 10 on the robot.

## Hardware

- **Car:** Elegoo Smart Robot Car V4.0
- **MCU:** Arduino Uno / Mega
- **Sensors:** HMC5883L magnetometer, ADXL345 accelerometer, wheel encoders
- **Camera:** iPhone (via Safari) or MacBook built-in
- **Communication:** WiFi (ESP8266/ESP32) or USB Serial

## License

This project is for educational purposes (Final Year Project).
