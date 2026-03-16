"""
ArUco Marker Detection Test -- Supports iPhone Continuity Camera
================================================================
Auto-scans all available cameras (including iPhone), then runs ArUco detection.

Prerequisites (for iPhone as camera):
  1. Mac and iPhone signed in with the same Apple ID
  2. On the same WiFi network (or Bluetooth enabled)
  3. macOS 13 Ventura+ and iOS 16+
  4. iPhone in lock screen near the Mac will auto-connect

Usage:
    python test_camera.py              # Auto-scan and select camera
    python test_camera.py --camera 1   # Use specific camera ID
    python test_camera.py --scan       # Scan only, no detection
    python test_camera.py --url http://192.168.1.x:8080/video  # IP camera mode

Controls:
    Hold ArUco markers in front of the camera
    Green border = detection success
    Press q to quit, press n to switch camera
"""

import cv2
import cv2.aruco as aruco
import numpy as np
import math
import sys
import argparse
import time

# Module-level constant (avoid per-frame allocation)
CORNER_COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]


def scan_cameras(max_id=5):
    """Scan all available camera devices, return list of available camera IDs."""
    print("Scanning available cameras...")
    print()
    available = []

    for cam_id in range(max_id):
        cap = cv2.VideoCapture(cam_id)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            backend = cap.getBackendName()

            # Try to read a frame to verify it's a real camera
            ret, frame = cap.read()
            if ret:
                available.append({
                    'id': cam_id,
                    'width': w,
                    'height': h,
                    'fps': fps,
                    'backend': backend,
                })
                print(f"  [OK] Camera {cam_id}: {w}x{h} @ {fps:.0f}fps ({backend})")
            else:
                print(f"  [!!] Camera {cam_id}: opened but no frame ({backend})")
            cap.release()
        # Brief pause to avoid overwhelming the camera subsystem
        time.sleep(0.05)

    print()
    if not available:
        print("[ERROR] No cameras found!")
        print()
        print("To use iPhone as camera:")
        print("  1. Make sure Mac and iPhone are signed in with the same Apple ID")
        print("  2. On the same WiFi network")
        print("  3. macOS 13+ / iOS 16+")
        print("  4. Place iPhone near Mac (lock screen)")
        print()
        print("Or use an IP camera app:")
        print("  1. Install 'DroidCam' or 'IP Webcam' or 'Camo' on iPhone")
        print("  2. Get the URL, then run:")
        print("     python test_camera.py --url http://YOUR_IP:PORT/video")
    else:
        print(f"Found {len(available)} available camera(s)")
        if len(available) > 1:
            print("  Hint: Camera 0 is usually the MacBook built-in camera")
            print("        Camera 1/2 is usually the iPhone Continuity Camera")

    return available


def preview_cameras(available):
    """Show preview of all available cameras, let user select."""
    if not available:
        return None

    print()
    print("Camera preview -- press number key to select, q to cancel")
    print()

    caps = []
    for cam in available:
        cap = cv2.VideoCapture(cam['id'])
        if cap.isOpened():
            caps.append((cam, cap))

    if not caps:
        print("[ERROR] Cannot open any camera")
        return None

    selected = None
    while True:
        frames = []
        for cam, cap in caps:
            ret, frame = cap.read()
            if ret:
                # Resize to thumbnail
                thumb = cv2.resize(frame, (320, 240))
                # Add label
                label = f"Camera {cam['id']}  ({cam['width']}x{cam['height']})"
                cv2.rectangle(thumb, (0, 0), (320, 30), (30, 30, 30), -1)
                cv2.putText(thumb, label, (5, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)
                cv2.putText(thumb, f"Press '{cam['id']}' to select", (5, 235),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)
                frames.append(thumb)

        if frames:
            # Stack thumbnails horizontally (max 4 per row)
            row_size = min(4, len(frames))
            rows = []
            for i in range(0, len(frames), row_size):
                row = frames[i:i + row_size]
                # Pad row if needed
                while len(row) < row_size:
                    row.append(np.zeros_like(row[0]))
                rows.append(np.hstack(row))
            grid = np.vstack(rows) if len(rows) > 1 else rows[0]
            cv2.imshow("Camera Preview - Press number to select, q to cancel", grid)

        key = cv2.waitKey(30) & 0xFF
        if key == ord('q'):
            break
        # Check if a valid camera number was pressed
        for cam, cap in caps:
            if key == ord(str(cam['id'])):
                selected = cam['id']
                break
        if selected is not None:
            break

    # Release preview captures
    for _, cap in caps:
        cap.release()
    cv2.destroyAllWindows()

    return selected


def run_aruco_detection(camera_source):
    """
    Run ArUco detection.
    camera_source: int (camera ID) or str (URL)
    """
    print()
    print("=" * 50)
    print("  ArUco Marker Detection -- Live Mode")
    print("=" * 50)
    print()

    # -- Open Camera -----------------------------------------------
    if isinstance(camera_source, str):
        print(f"Connecting to IP camera: {camera_source}")
        cap = cv2.VideoCapture(camera_source)
    else:
        print(f"Opening camera {camera_source}...")
        cap = cv2.VideoCapture(camera_source)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open camera {camera_source}")
        return

    # Set resolution (may be ignored by some cameras)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[OK] Camera opened: {w}x{h}")
    print()
    print("Hold ArUco markers in front of camera")
    print("Press q to quit")
    print()

    # -- ArUco Setup -----------------------------------------------
    aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    if hasattr(aruco, 'DetectorParameters'):
        params = aruco.DetectorParameters()
    else:
        params = aruco.DetectorParameters_create()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

    detector = None
    if hasattr(aruco, 'ArucoDetector'):
        detector = aruco.ArucoDetector(aruco_dict, params)

    # -- Homography for coordinate mapping -------------------------
    ANCHOR_IDS = {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (1.0, 1.0), 3: (0.0, 1.0)}
    ROBOT_ID = 10
    H_matrix = None
    detected_ever = set()

    # FPS counter
    fps_time = time.time()
    fps_count = 0
    fps_display = 0.0

    # -- Main Loop -------------------------------------------------
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # FPS
            fps_count += 1
            if time.time() - fps_time >= 1.0:
                fps_display = fps_count / (time.time() - fps_time)
                fps_count = 0
                fps_time = time.time()

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Detect
            if detector is not None:
                corners, ids, _ = detector.detectMarkers(gray)
            else:
                corners, ids, _ = aruco.detectMarkers(gray, aruco_dict, parameters=params)

            fh, fw = frame.shape[:2]

            # -- Top status bar ------------------------------------
            cv2.rectangle(frame, (0, 0), (fw, 40), (30, 30, 30), -1)
            cv2.putText(frame, f"FPS: {fps_display:.0f}", (fw - 100, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)

            if ids is not None and len(ids) > 0:
                aruco.drawDetectedMarkers(frame, corners, ids)
                ids_flat = ids.flatten()
                detected_ever.update(ids_flat.tolist())

                # Status text
                id_text = "Detected: " + ", ".join([f"ID {i}" for i in sorted(ids_flat)])
                cv2.putText(frame, id_text, (10, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 100), 2)

                # Per-marker info
                for i, mid in enumerate(ids_flat):
                    c = corners[i][0]
                    cx = int(np.mean(c[:, 0]))
                    cy = int(np.mean(c[:, 1]))

                    # Center dot
                    cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)
                    cv2.circle(frame, (cx, cy), 6, (255, 255, 255), 1)

                    # Size info
                    diag = np.linalg.norm(c[0] - c[2])
                    label = f"ID:{mid}"
                    cv2.putText(frame, label, (cx + 12, cy - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 2)
                    cv2.putText(frame, f"{diag:.0f}px", (cx + 12, cy + 16),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)

                    # Draw corner order (0=TL, 1=TR, 2=BR, 3=BL)
                    for j in range(4):
                        pt = tuple(c[j].astype(int))
                        cv2.circle(frame, pt, 4, CORNER_COLORS[j], -1)

                # -- Calibration attempt ---------------------------
                all_anchors = all(aid in ids_flat for aid in ANCHOR_IDS)
                if all_anchors:
                    src_pts = []
                    dst_pts = []
                    for aid, (rx, ry) in ANCHOR_IDS.items():
                        idx = np.where(ids_flat == aid)[0][0]
                        mc = corners[idx][0]
                        src_pts.append([float(np.mean(mc[:, 0])), float(np.mean(mc[:, 1]))])
                        dst_pts.append([rx, ry])
                    src_pts = np.array(src_pts, dtype=np.float32)
                    dst_pts = np.array(dst_pts, dtype=np.float32)
                    H_matrix, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

                if H_matrix is not None:
                    cv2.putText(frame, "CALIBRATED", (fw - 220, 28),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                # -- Robot pose ------------------------------------
                if H_matrix is not None and ROBOT_ID in ids_flat:
                    idx = np.where(ids_flat == ROBOT_ID)[0][0]
                    rc = corners[idx][0]
                    rcx = float(np.mean(rc[:, 0]))
                    rcy = float(np.mean(rc[:, 1]))

                    pt = np.array([[[rcx, rcy]]], dtype=np.float32)
                    world = cv2.perspectiveTransform(pt, H_matrix)
                    wx, wy = float(world[0][0][0]), float(world[0][0][1])

                    # Heading
                    top_mid = (rc[0] + rc[1]) / 2.0
                    bot_mid = (rc[2] + rc[3]) / 2.0
                    pt_top = cv2.perspectiveTransform(
                        np.array([[[float(top_mid[0]), float(top_mid[1])]]], dtype=np.float32),
                        H_matrix)
                    pt_bot = cv2.perspectiveTransform(
                        np.array([[[float(bot_mid[0]), float(bot_mid[1])]]], dtype=np.float32),
                        H_matrix)
                    dx = float(pt_top[0][0][0] - pt_bot[0][0][0])
                    dy = float(pt_top[0][0][1] - pt_bot[0][0][1])
                    theta = math.atan2(dy, dx)

                    # Green bar with pose
                    cv2.rectangle(frame, (0, fh - 50), (fw, fh), (0, 80, 0), -1)
                    pose_text = f"ROBOT  x={wx:.3f}m  y={wy:.3f}m  heading={math.degrees(theta):.1f} deg"
                    cv2.putText(frame, pose_text, (10, fh - 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)

                    # Draw heading arrow on the marker
                    arrow_len = 60
                    ax = int(rcx + arrow_len * math.cos(theta))
                    ay = int(rcy - arrow_len * math.sin(theta))
                    cv2.arrowedLine(frame, (int(rcx), int(rcy)), (ax, ay),
                                    (0, 255, 0), 3, tipLength=0.3)

            else:
                cv2.putText(frame, "No markers detected -- hold marker in front of camera", (10, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 100, 255), 2)

            # -- Bottom info panel ---------------------------------
            info_y = fh - 110 if H_matrix is None or ids is None or ROBOT_ID not in (ids.flatten() if ids is not None else []) else fh - 155
            cv2.rectangle(frame, (0, info_y), (380, info_y + 55), (40, 40, 40), -1)
            cv2.putText(frame, f"History: {sorted(detected_ever)}", (10, info_y + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)
            cal_text = "Coordinate: READY" if H_matrix is not None else "Coordinate: need 4 anchors (ID 0-3)"
            cal_color = (0, 200, 0) if H_matrix is not None else (0, 100, 255)
            cv2.putText(frame, cal_text, (10, info_y + 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, cal_color, 1)

            # -- Show ----------------------------------------------
            cv2.imshow("ArUco Detection (q=quit)", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()

    print()
    print(f"Detected marker IDs: {sorted(detected_ever)}")
    print("Test complete.")


def main():
    parser = argparse.ArgumentParser(
        description="ArUco Marker Detection Test -- MacBook/iPhone/IP Camera")
    parser.add_argument("--camera", type=int, default=None,
                        help="Camera ID (skip scan)")
    parser.add_argument("--url", type=str, default=None,
                        help="IP camera URL (e.g. http://192.168.1.x:8080/video)")
    parser.add_argument("--scan", action="store_true",
                        help="Scan only, no detection")
    args = parser.parse_args()

    # IP Camera mode
    if args.url:
        run_aruco_detection(args.url)
        return

    # Direct camera ID
    if args.camera is not None:
        run_aruco_detection(args.camera)
        return

    # Auto-scan mode
    available = scan_cameras()

    if args.scan:
        return

    if not available:
        print()
        print("Alternative: Use an iPhone IP camera app")
        print("  1. Install free app 'DroidCam' from the App Store on iPhone")
        print("  2. Connect Mac and iPhone to the same WiFi")
        print("  3. Open the app and note the IP and port")
        print("  4. Run: python test_camera.py --url http://IP:PORT/video")
        return

    if len(available) == 1:
        print(f"-> Only one camera found, using Camera {available[0]['id']}")
        run_aruco_detection(available[0]['id'])
    else:
        # Let user pick
        selected = preview_cameras(available)
        if selected is not None:
            print(f"-> Selected Camera {selected}")
            run_aruco_detection(selected)
        else:
            print("Cancelled.")


if __name__ == "__main__":
    main()
