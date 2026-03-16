"""
ArUco Vision Localization System
================================
Top-down camera ArUco Marker localization for AGV indoor navigation.
Provides real-time (x, y, theta) pose estimation via perspective transform (homography).

Architecture:
  1. Four anchor markers define the real-world coordinate frame.
  2. A homography matrix maps pixel coordinates -> metric world coordinates.
  3. The robot marker's center gives (x, y); corner geometry gives heading (theta).
  4. EMA (Exponential Moving Average) filters smooth all outputs.
  5. Lost-marker fallback holds last valid pose for a configurable number of frames.

Usage:
  tracker = ArucoLocalization(camera_id=0)
  tracker.ANCHOR_IDS = {0: (0,0), 1: (2,0), 2: (2,2), 3: (0,2)}
  tracker.ROBOT_MARKER_ID = 10
  tracker.start()
  x, y, theta, valid = tracker.get_pose()
"""

import cv2
import cv2.aruco as aruco
import numpy as np
import threading
import time
import math
import json
import os
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CAMERA_RES = (1280, 720)
DEFAULT_EMA_ALPHA = 0.4          # Lower = smoother, higher = more responsive
DEFAULT_LOST_TIMEOUT_FRAMES = 15  # Hold last pose for this many frames
DEFAULT_CALIBRATION_FILE = "homography_calibration.json"


class ArucoLocalization:
    """
    Top-down camera ArUco Marker localization system.
    Provides thread-safe, real-time (x, y, theta) pose estimation.
    """

    def __init__(self, camera_id=0, dictionary_id=aruco.DICT_4X4_50,
                 marker_size_m=0.05, ema_alpha=DEFAULT_EMA_ALPHA):
        # ── Camera & ArUco ────────────────────────────────────────
        self.camera_id = camera_id
        self.marker_size_m = marker_size_m
        self.aruco_dict = aruco.getPredefinedDictionary(dictionary_id)

        # Build detector parameters with tuning for indoor lighting
        if hasattr(aruco, 'DetectorParameters'):
            self.aruco_params = aruco.DetectorParameters()
        else:
            self.aruco_params = aruco.DetectorParameters_create()

        # Tune detection for robustness
        self.aruco_params.adaptiveThreshWinSizeMin = 3
        self.aruco_params.adaptiveThreshWinSizeMax = 23
        self.aruco_params.adaptiveThreshWinSizeStep = 10
        self.aruco_params.adaptiveThreshConstant = 7
        self.aruco_params.minMarkerPerimeterRate = 0.02
        self.aruco_params.maxMarkerPerimeterRate = 4.0
        self.aruco_params.polygonalApproxAccuracyRate = 0.05
        self.aruco_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

        # Build detector (OpenCV 4.7+ API)
        self._detector = None
        if hasattr(aruco, 'ArucoDetector'):
            self._detector = aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        self.cap = None

        # ── Threading & Control ───────────────────────────────────
        self.running = False
        self._thread = None
        self._lock = threading.Lock()

        # ── Pose State ────────────────────────────────────────────
        self._x = 0.0
        self._y = 0.0
        self._theta = 0.0
        self._valid = False
        self._lost_frames = 0
        self._lost_timeout = DEFAULT_LOST_TIMEOUT_FRAMES
        self._ema_alpha = ema_alpha

        # ── Homography ────────────────────────────────────────────
        self.homography_matrix = None
        self._calibration_file = DEFAULT_CALIBRATION_FILE
        self._calibrated = False

        # ── Anchor & Robot Configuration ──────────────────────────
        # Keys: marker IDs, Values: (real_x_m, real_y_m)
        self.ANCHOR_IDS = {
            0: (0.0, 0.0),    # Top-Left / Origin
            1: (1.0, 0.0),    # Top-Right
            2: (1.0, 1.0),    # Bottom-Right
            3: (0.0, 1.0),    # Bottom-Left
        }
        self.ROBOT_MARKER_ID = 10

        # -- Debug / Display -----------------------------------------
        self.latest_frame = None       # Annotated frame for display
        self._frame_lock = threading.Lock()  # Lock for latest_frame
        self.show_debug = True         # Draw debug info on frame
        self._fps = 0.0
        self._anchor_status = {}       # {id: True/False} -- which anchors are visible
        self._callback = None          # Optional callback: fn(x, y, theta, valid)
        self._last_calibration_time = 0.0  # Cooldown timer for recalibration
        self._calibration_cooldown = 5.0   # Seconds between recalibrations
        self._H_inv_cache = None           # Cached inverse homography for grid drawing

    # ==================================================================
    # Public API
    # ==================================================================

    def start(self):
        """Start the background camera capture and processing thread."""
        self.cap = cv2.VideoCapture(self.camera_id)
        if not self.cap.isOpened():
            print(f"[ArUco] ERROR: Cannot open camera {self.camera_id}")
            return False

        # Set resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, DEFAULT_CAMERA_RES[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, DEFAULT_CAMERA_RES[1])

        # Try to reduce buffer delay (grab latest frame)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Load persisted calibration if available
        self._load_calibration()

        self.running = True
        self._thread = threading.Thread(target=self._processing_loop, daemon=True)
        self._thread.start()
        print(f"[ArUco] Localization started (camera={self.camera_id})")
        return True

    def stop(self):
        """Stop the camera thread and release resources."""
        self.running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        if self.cap is not None:
            self.cap.release()
        cv2.destroyAllWindows()
        print("[ArUco] Localization stopped.")

    def get_pose(self):
        """
        Thread-safe getter for current robot pose.

        Returns:
            tuple: (x, y, theta, is_valid)
                - x: meters in world frame
                - y: meters in world frame
                - theta: radians, heading angle (0 = +X axis, CCW positive)
                - is_valid: True if pose is fresh, False if stale/lost
        """
        with self._lock:
            return self._x, self._y, self._theta, self._valid

    def get_status(self):
        """
        Get system status info for display.

        Returns:
            dict with keys: calibrated, fps, anchor_status, valid, lost_frames
        """
        with self._lock:
            return {
                "calibrated": self._calibrated,
                "fps": self._fps,
                "anchor_status": dict(self._anchor_status),
                "valid": self._valid,
                "lost_frames": self._lost_frames,
            }

    def set_callback(self, fn):
        """Set a callback function called on each valid pose update: fn(x, y, theta, valid)."""
        self._callback = fn

    def force_recalibrate(self):
        """Force recalibration on next frame (discard current homography)."""
        self.homography_matrix = None
        self._calibrated = False
        self._H_inv_cache = None
        print("[ArUco] Forced recalibration -- waiting for all 4 anchors...")

    def is_calibrated(self):
        """Check if homography is calibrated."""
        return self._calibrated

    # ==================================================================
    # Calibration Persistence
    # ==================================================================

    def _get_calibration_path(self):
        """Get full path to calibration file (same directory as this script)."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, self._calibration_file)

    def _save_calibration(self):
        """Save homography matrix and anchor config to JSON."""
        if self.homography_matrix is None:
            return
        path = self._get_calibration_path()
        data = {
            "homography": self.homography_matrix.tolist(),
            "anchor_ids": {str(k): list(v) for k, v in self.ANCHOR_IDS.items()},
            "robot_marker_id": self.ROBOT_MARKER_ID,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"[ArUco] Calibration saved to {path}")
        except Exception as e:
            print(f"[ArUco] WARNING: Could not save calibration: {e}")

    def _load_calibration(self):
        """Load persisted homography matrix if available and anchor config matches."""
        path = self._get_calibration_path()
        if not os.path.exists(path):
            return False

        try:
            with open(path, 'r') as f:
                data = json.load(f)

            # Verify anchor config still matches
            saved_anchors = {int(k): tuple(v) for k, v in data["anchor_ids"].items()}
            if saved_anchors != self.ANCHOR_IDS:
                print("[ArUco] Saved calibration anchors don't match current config -- recalibrating.")
                return False

            self.homography_matrix = np.array(data["homography"], dtype=np.float64)
            self._calibrated = True
            print(f"[ArUco] Loaded calibration from {path} (saved {data.get('timestamp', '?')})")
            return True

        except Exception as e:
            print(f"[ArUco] WARNING: Could not load calibration: {e}")
            return False

    # ==================================================================
    # Homography Calibration
    # ==================================================================

    def _calibrate_homography(self, ids, corners):
        """
        Calculate the homography matrix from detected anchor markers.

        Uses cv2.findHomography for robustness (handles >4 points if extra
        anchors are added in the future; RANSAC filtering).

        Returns True if calibration succeeded.
        """
        if ids is None:
            return False

        ids_flat = ids.flatten()
        src_pts = []  # pixel coordinates
        dst_pts = []  # real-world coordinates

        for anchor_id, (real_x, real_y) in self.ANCHOR_IDS.items():
            if anchor_id in ids_flat:
                idx = np.where(ids_flat == anchor_id)[0][0]
                marker_corners = corners[idx][0]
                # Use marker center as the reference point
                center_px = float(np.mean(marker_corners[:, 0]))
                center_py = float(np.mean(marker_corners[:, 1]))
                src_pts.append([center_px, center_py])
                dst_pts.append([real_x, real_y])

        if len(src_pts) < 4:
            return False

        src_pts = np.array(src_pts, dtype=np.float32)
        dst_pts = np.array(dst_pts, dtype=np.float32)

        # Use findHomography instead of getPerspectiveTransform for robustness
        matrix, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

        if matrix is None:
            print("[ArUco] WARNING: findHomography returned None")
            return False

        self.homography_matrix = matrix
        self._calibrated = True
        self._H_inv_cache = None  # Invalidate inverse cache
        self._last_calibration_time = time.time()

        # Save for next session
        self._save_calibration()

        print("[ArUco] OK: Homography calibrated successfully")
        return True

    def _transform_point(self, pixel_x, pixel_y):
        """Transform a pixel coordinate to real-world (meters) using the homography."""
        if self.homography_matrix is None:
            return None
        pt = np.array([[[pixel_x, pixel_y]]], dtype=np.float32)
        result = cv2.perspectiveTransform(pt, self.homography_matrix)
        return float(result[0][0][0]), float(result[0][0][1])

    # ==================================================================
    # Pose Extraction
    # ==================================================================

    def _extract_robot_pose(self, ids, corners):
        """
        Extract robot (x, y, theta) from the robot marker.

        Heading is computed from the ArUco marker's edge vectors,
        transformed into world coordinates.

        Returns (x, y, theta) or None if robot marker not found.
        """
        if ids is None or self.homography_matrix is None:
            return None

        ids_flat = ids.flatten()
        if self.ROBOT_MARKER_ID not in ids_flat:
            return None

        idx = np.where(ids_flat == self.ROBOT_MARKER_ID)[0][0]
        robot_corners = corners[idx][0]  # shape: (4, 2) -- TL, TR, BR, BL

        # -- Position: marker center --------------------------------
        center_px = float(np.mean(robot_corners[:, 0]))
        center_py = float(np.mean(robot_corners[:, 1]))
        world_center = self._transform_point(center_px, center_py)
        if world_center is None:
            return None
        real_x, real_y = world_center

        # -- Heading: from marker edge geometry ---------------------
        # ArUco corners order: [TL, TR, BR, BL]
        # "Forward" direction: from bottom edge midpoint -> top edge midpoint
        #   top_mid = (TL + TR) / 2
        #   bot_mid = (BL + BR) / 2
        #   forward_vector = top_mid - bot_mid
        top_mid_px = (robot_corners[0] + robot_corners[1]) / 2.0
        bot_mid_px = (robot_corners[2] + robot_corners[3]) / 2.0

        pt_top = self._transform_point(float(top_mid_px[0]), float(top_mid_px[1]))
        pt_bot = self._transform_point(float(bot_mid_px[0]), float(bot_mid_px[1]))

        if pt_top is None or pt_bot is None:
            return None

        dx = pt_top[0] - pt_bot[0]
        dy = pt_top[1] - pt_bot[1]
        theta = math.atan2(dy, dx)

        return real_x, real_y, theta

    # ==================================================================
    # EMA Filter with Angle Wrapping
    # ==================================================================

    def _update_pose_ema(self, x, y, theta):
        """Apply EMA (Exponential Moving Average) filter to smooth the pose."""
        alpha = self._ema_alpha

        with self._lock:
            if not self._valid:
                # First valid reading -- initialize directly
                self._x = x
                self._y = y
                self._theta = theta
                self._valid = True
                self._lost_frames = 0
            else:
                # Smooth position
                self._x = alpha * x + (1.0 - alpha) * self._x
                self._y = alpha * y + (1.0 - alpha) * self._y

                # Smooth angle with wrap-around handling
                angle_diff = theta - self._theta
                if angle_diff > math.pi:
                    angle_diff -= 2.0 * math.pi
                elif angle_diff < -math.pi:
                    angle_diff += 2.0 * math.pi
                self._theta += alpha * angle_diff

                # Normalize theta to [-pi, pi] (single-op, no loop)
                self._theta = math.atan2(math.sin(self._theta), math.cos(self._theta))

                self._valid = True
                self._lost_frames = 0

    def _handle_lost_marker(self):
        """Handle frames where the robot marker is not detected."""
        with self._lock:
            self._lost_frames += 1
            if self._lost_frames > self._lost_timeout:
                self._valid = False
                # Keep last known x, y, theta -- just mark as invalid

    # ==================================================================
    # Debug Drawing
    # ==================================================================

    def _draw_debug_overlay(self, frame, ids, corners):
        """Draw debug information on the camera frame."""
        h, w = frame.shape[:2]

        # -- Status bar at top --------------------------------------
        status_color = (0, 180, 0) if self._calibrated else (0, 100, 255)
        status_text = "CALIBRATED" if self._calibrated else "WAITING FOR ANCHORS"
        cv2.rectangle(frame, (0, 0), (w, 32), (30, 30, 30), -1)
        cv2.putText(frame, f"[ArUco] {status_text}  |  FPS: {self._fps:.0f}",
                    (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_color, 1)

        # -- Anchor status indicators -------------------------------
        ids_flat = ids.flatten() if ids is not None else []
        y_off = 50
        for aid, (rx, ry) in self.ANCHOR_IDS.items():
            found = aid in ids_flat
            self._anchor_status[aid] = found
            color = (0, 220, 0) if found else (0, 0, 200)
            icon = "[*]" if found else "[ ]"
            cv2.putText(frame, f"{icon} Anchor {aid}: ({rx:.1f}, {ry:.1f})m",
                        (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
            y_off += 20

        # -- Robot pose readout ------------------------------------
        with self._lock:
            if self._valid:
                pose_color = (0, 255, 100)
                cv2.putText(frame,
                            f"Robot: x={self._x:.3f}m  y={self._y:.3f}m  "
                            f"th={math.degrees(self._theta):.1f}deg",
                            (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            pose_color, 1)
            else:
                cv2.putText(frame, "Robot: NOT DETECTED",
                            (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            (0, 0, 200), 1)
                if self._lost_frames > 0:
                    cv2.putText(frame, f"Lost: {self._lost_frames} frames",
                                (10, h - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                (0, 100, 255), 1)

        # ── Draw world-coordinate grid on frame ───────────────────
        if self._calibrated and self.homography_matrix is not None:
            self._draw_world_grid(frame)

    def _draw_world_grid(self, frame):
        """Draw a metric grid overlay on the camera frame using inverse homography."""
        # Use cached inverse to avoid per-frame matrix inversion
        if self._H_inv_cache is None:
            try:
                self._H_inv_cache = np.linalg.inv(self.homography_matrix)
            except np.linalg.LinAlgError:
                return
        H_inv = self._H_inv_cache
        try:
            pass  # H_inv already computed
        except np.linalg.LinAlgError:
            return

        # Determine grid range from anchor positions
        all_x = [v[0] for v in self.ANCHOR_IDS.values()]
        all_y = [v[1] for v in self.ANCHOR_IDS.values()]
        x_min, x_max = min(all_x), max(all_x)
        y_min, y_max = min(all_y), max(all_y)

        step = 0.25  # 25 cm grid lines

        # Draw vertical grid lines (constant x)
        x = x_min
        while x <= x_max + 0.01:
            pts_world = np.array([[[x, y_min]], [[x, y_max]]], dtype=np.float32)
            pts_pixel = cv2.perspectiveTransform(pts_world, H_inv)
            p1 = tuple(pts_pixel[0][0].astype(int))
            p2 = tuple(pts_pixel[1][0].astype(int))
            cv2.line(frame, p1, p2, (60, 60, 60), 1)
            # Label
            cv2.putText(frame, f"{x:.1f}", p1,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (100, 100, 100), 1)
            x += step

        # Draw horizontal grid lines (constant y)
        y = y_min
        while y <= y_max + 0.01:
            pts_world = np.array([[[x_min, y]], [[x_max, y]]], dtype=np.float32)
            pts_pixel = cv2.perspectiveTransform(pts_world, H_inv)
            p1 = tuple(pts_pixel[0][0].astype(int))
            p2 = tuple(pts_pixel[1][0].astype(int))
            cv2.line(frame, p1, p2, (60, 60, 60), 1)
            y += step

    # ==================================================================
    # Main Processing Loop (background thread)
    # ==================================================================

    def _processing_loop(self):
        """Main capture + detect + track loop running in a background thread."""
        frame_count = 0
        fps_timer = time.time()

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # ── FPS calculation ───────────────────────────────────
            frame_count += 1
            elapsed = time.time() - fps_timer
            if elapsed >= 1.0:
                self._fps = frame_count / elapsed
                frame_count = 0
                fps_timer = time.time()

            # ── Detect ArUco markers ──────────────────────────────
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if self._detector is not None:
                corners, ids, rejected = self._detector.detectMarkers(gray)
            else:
                corners, ids, rejected = aruco.detectMarkers(
                    gray, self.aruco_dict, parameters=self.aruco_params)

            # Draw detected markers
            if ids is not None and len(ids) > 0:
                aruco.drawDetectedMarkers(frame, corners, ids)

            # ── Calibrate homography if not yet done ──────────────
            if not self._calibrated:
                if ids is not None:
                    self._calibrate_homography(ids, corners)

            # ── Extract robot pose ────────────────────────────────
            if self._calibrated:
                pose = self._extract_robot_pose(ids, corners)
                if pose is not None:
                    x, y, theta = pose
                    self._update_pose_ema(x, y, theta)

                    # Fire callback if set
                    if self._callback:
                        try:
                            self._callback(x, y, theta, True)
                        except Exception:
                            pass
                else:
                    self._handle_lost_marker()

                # Recalibrate periodically if all anchors are visible
                # (handles camera bumps / shifts) -- with cooldown
                if ids is not None:
                    elapsed_since_cal = time.time() - self._last_calibration_time
                    if elapsed_since_cal >= self._calibration_cooldown:
                        ids_flat = ids.flatten()
                        all_anchors_visible = all(
                            aid in ids_flat for aid in self.ANCHOR_IDS
                        )
                        if all_anchors_visible:
                            self._calibrate_homography(ids, corners)

            # ── Debug overlay ─────────────────────────────────────
            if self.show_debug:
                self._draw_debug_overlay(frame, ids, corners)

            # Store annotated frame for external consumers (thread-safe)
            with self._frame_lock:
                self.latest_frame = frame

            # Yield CPU — target ~30 FPS processing
            time.sleep(0.005)


# ======================================================================
# Utility: Generate Printable ArUco Marker PDFs
# ======================================================================

def generate_marker_images(output_dir="aruco_markers", dictionary_id=aruco.DICT_4X4_50,
                           marker_ids=None, marker_size_px=200, border_bits=1):
    """
    Generate ArUco marker images for printing.

    Args:
        output_dir: Directory to save marker images
        dictionary_id: ArUco dictionary type
        marker_ids: List of IDs to generate. Default: [0,1,2,3,10]
        marker_size_px: Size of the marker image in pixels
        border_bits: Width of the black border around the marker
    """
    if marker_ids is None:
        marker_ids = [0, 1, 2, 3, 10]

    os.makedirs(output_dir, exist_ok=True)
    aruco_dict = aruco.getPredefinedDictionary(dictionary_id)

    for mid in marker_ids:
        if hasattr(aruco, 'generateImageMarker'):
            img = aruco.generateImageMarker(aruco_dict, mid, marker_size_px, borderBits=border_bits)
        else:
            img = aruco.drawMarker(aruco_dict, mid, marker_size_px, borderBits=border_bits)

        # Add white padding and label
        padded = np.ones((marker_size_px + 80, marker_size_px + 40), dtype=np.uint8) * 255
        y_off = 20
        x_off = 20
        padded[y_off:y_off + marker_size_px, x_off:x_off + marker_size_px] = img
        cv2.putText(padded, f"ID: {mid}  (DICT_4X4_50)",
                    (10, marker_size_px + 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)

        filepath = os.path.join(output_dir, f"aruco_marker_{mid}.png")
        cv2.imwrite(filepath, padded)
        print(f"  Saved: {filepath}")

    print(f"\n[ArUco] Generated {len(marker_ids)} markers in '{output_dir}/'")
    print("  -> Print these at a fixed size (e.g. 5cm x 5cm).")
    print("  -> Place IDs 0-3 at the four corners of your arena.")
    print("  -> Attach ID 10 on top of your robot.")


# ======================================================================
# Utility: Calibration Accuracy Validator
# ======================================================================

def validate_calibration(tracker):
    """
    Interactive calibration accuracy test.
    Place the robot marker at known positions and compare measured vs expected.
    """
    print("\n" + "=" * 60)
    print("  CALIBRATION ACCURACY VALIDATION")
    print("=" * 60)
    print("Place the robot marker at known positions and press ENTER.")
    print("Type 'q' to finish.\n")

    errors = []
    while True:
        try:
            inp = input("Expected position (x y) in meters, or 'q': ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if inp.lower() == 'q':
            break

        try:
            parts = inp.split()
            expected_x = float(parts[0])
            expected_y = float(parts[1])
        except (ValueError, IndexError):
            print("  Invalid input. Format: x y (e.g. '0.5 0.3')")
            continue

        # Take average of 10 readings
        readings = []
        for _ in range(10):
            x, y, theta, valid = tracker.get_pose()
            if valid:
                readings.append((x, y, theta))
            time.sleep(0.05)

        if not readings:
            print("  ✘ No valid pose detected!")
            continue

        avg_x = sum(r[0] for r in readings) / len(readings)
        avg_y = sum(r[1] for r in readings) / len(readings)
        avg_th = sum(r[2] for r in readings) / len(readings)

        err_x = avg_x - expected_x
        err_y = avg_y - expected_y
        err_dist = math.sqrt(err_x**2 + err_y**2)
        errors.append(err_dist)

        print(f"  Expected:  ({expected_x:.3f}, {expected_y:.3f})")
        print(f"  Measured:  ({avg_x:.3f}, {avg_y:.3f})")
        print(f"  Error:     dx={err_x:+.3f}m  dy={err_y:+.3f}m  "
              f"dist={err_dist:.3f}m  ({err_dist*100:.1f}cm)")
        print(f"  Heading:   {math.degrees(avg_th):.1f}°")
        print()

    if errors:
        avg_err = sum(errors) / len(errors)
        max_err = max(errors)
        print(f"\nSummary: {len(errors)} test points")
        print(f"  Mean error:  {avg_err:.3f}m ({avg_err*100:.1f}cm)")
        print(f"  Max error:   {max_err:.3f}m ({max_err*100:.1f}cm)")
        if avg_err < 0.02:
            print("  Rating: *** Excellent (<2cm)")
        elif avg_err < 0.05:
            print("  Rating: ** Good (<5cm)")
        else:
            print("  Rating: * Needs improvement -- check marker placement and camera angle")


# ======================================================================
# Standalone Test & Demo
# ======================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ArUco Vision Localization System")
    parser.add_argument("--camera", type=int, default=0, help="Camera device ID")
    parser.add_argument("--generate", action="store_true",
                        help="Generate printable ArUco marker images and exit")
    parser.add_argument("--validate", action="store_true",
                        help="Run calibration accuracy validation after initialization")
    parser.add_argument("--recalibrate", action="store_true",
                        help="Force recalibration (ignore saved homography)")
    parser.add_argument("--arena-width", type=float, default=1.0,
                        help="Arena width in meters (default: 1.0)")
    parser.add_argument("--arena-height", type=float, default=1.0,
                        help="Arena height in meters (default: 1.0)")
    parser.add_argument("--robot-id", type=int, default=10,
                        help="Robot marker ID (default: 10)")
    args = parser.parse_args()

    # ── Marker generation mode ────────────────────────────────────
    if args.generate:
        print("[ArUco] Generating marker images...")
        generate_marker_images(marker_ids=[0, 1, 2, 3, args.robot_id])
        sys.exit(0)

    # ── Live tracking mode ────────────────────────────────────────
    print("[ArUco] Starting live localization...")
    print(f"  Camera:   {args.camera}")
    print(f"  Arena:    {args.arena_width}m × {args.arena_height}m")
    print(f"  Robot ID: {args.robot_id}")
    print()

    tracker = ArucoLocalization(camera_id=args.camera)

    # Configure arena
    W, H = args.arena_width, args.arena_height
    tracker.ANCHOR_IDS = {
        0: (0.0, 0.0),    # Top-Left
        1: (W,   0.0),    # Top-Right
        2: (W,   H),      # Bottom-Right
        3: (0.0, H),      # Bottom-Left
    }
    tracker.ROBOT_MARKER_ID = args.robot_id

    if args.recalibrate:
        # Delete saved calibration
        cal_path = tracker._get_calibration_path()
        if os.path.exists(cal_path):
            os.remove(cal_path)
            print("[ArUco] Deleted saved calibration -- will recalibrate from scratch.")

    if not tracker.start():
        print("[ArUco] FATAL: Cannot start camera. Exiting.")
        sys.exit(1)

    # Optional: run validation mode
    if args.validate:
        print("[ArUco] Waiting 5 seconds for calibration...")
        time.sleep(5)
        if tracker.is_calibrated():
            validate_calibration(tracker)
        else:
            print("[ArUco] ERROR: Not calibrated yet - ensure all 4 anchor markers are visible.")

    # -- Main display loop -----------------------------------------
    print("\nControls:")
    print("  q     -- Quit")
    print("  c     -- Force recalibration")
    print("  s     -- Print current pose to console")
    print("  v     -- Start validation mode")
    print()

    try:
        while True:
            frame = tracker.latest_frame
            if frame is not None:
                cv2.imshow("ArUco Localization", frame)

            key = cv2.waitKey(30) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('c'):
                tracker.force_recalibrate()
            elif key == ord('s'):
                x, y, th, valid = tracker.get_pose()
                status = tracker.get_status()
                print(f"  Pose: x={x:.3f}m  y={y:.3f}m  theta={math.degrees(th):.1f}deg  "
                      f"valid={valid}  fps={status['fps']:.0f}")
            elif key == ord('v'):
                if tracker.is_calibrated():
                    validate_calibration(tracker)
                else:
                    print("  Not calibrated yet!")

    except KeyboardInterrupt:
        pass
    finally:
        tracker.stop()
