# Smart Car Autonomous Navigation System

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
