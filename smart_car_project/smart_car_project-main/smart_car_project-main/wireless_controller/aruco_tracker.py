import cv2
import cv2.aruco as aruco
import numpy as np
import threading
import time
import math

class ArucoLocalization:
    """
    Top-down camera ArUco Marker localization system.
    Provides real-time (x, y, theta) pose estimation based on perspective transform.
    """
    def __init__(self, camera_id=0, dictionary_id=aruco.DICT_4X4_50, marker_size=0.05):
        # Camera & ArUco settings
        self.camera_id = camera_id
        self.marker_size = marker_size  # meters (for reference if needed)
        self.aruco_dict = aruco.getPredefinedDictionary(dictionary_id)
        self.aruco_params = aruco.DetectorParameters_create() if hasattr(aruco, 'DetectorParameters_create') else aruco.DetectorParameters()
        self.cap = None

        # Threading & Control
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        # State Variables
        self._current_x = 0.0
        self._current_y = 0.0
        self._current_theta = 0.0
        self._has_valid_pose = False
        
        # Homography (Perspective Transform) Matrix
        self.homography_matrix = None
        
        # Calibration Settings
        # Define 4 anchor markers IDs and their real-world (x, y) coordinates in meters
        self.ANCHOR_IDS = {
            1: (0.0, 0.0),   # TL (Top-Left) or Origin
            2: (1.0, 0.0),   # TR (Top-Right)
            3: (1.0, 1.0),   # BR (Bottom-Right)
            4: (0.0, 1.0)    # BL (Bottom-Left)
        }
        self.ROBOT_MARKER_ID = 10 # The ID of the marker on top of the car

        # Optional: For debugging/display
        self.latest_frame = None

    def start(self):
        """Start the background camera thread."""
        self.cap = cv2.VideoCapture(self.camera_id)
        if not self.cap.isOpened():
            print(f"Error: Could not open camera {self.camera_id}.")
            return False
            
        # Try to set high resolution for better detection
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("Aruco Localization started.")
        return True

    def stop(self):
        """Stop the camera and thread."""
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        if self.cap is not None:
            self.cap.release()
        cv2.destroyAllWindows()
        print("Aruco Localization stopped.")

    def get_pose(self):
        """Thread-safe getter for the current pose: (x, y, theta, is_valid)."""
        with self.lock:
            return self._current_x, self._current_y, self._current_theta, self._has_valid_pose

    def calibrate_homography(self, ids, corners):
        """
        Calculates the perspective transform matrix from the four anchor tags.
        """
        if ids is None or len(ids) < 4:
            return False

        src_pts = []
        dst_pts = []
        
        ids_flat = ids.flatten()
        found_anchors = 0
        
        for anchor_id, (real_x, real_y) in self.ANCHOR_IDS.items():
            if anchor_id in ids_flat:
                # Find the index of this anchor in the detected ids
                idx = np.where(ids_flat == anchor_id)[0][0]
                # Get the center pixel of this marker
                marker_corners = corners[idx][0]
                center_x = np.mean(marker_corners[:, 0])
                center_y = np.mean(marker_corners[:, 1])
                
                src_pts.append([center_x, center_y])
                dst_pts.append([real_x, real_y])
                found_anchors += 1

        if found_anchors >= 4:
            src_pts = np.array(src_pts, dtype=np.float32)
            dst_pts = np.array(dst_pts, dtype=np.float32)
            # Compute perspective transform
            matrix, _ = cv2.findHomography(src_pts, dst_pts)
            self.homography_matrix = matrix
            print("INFO: Homography matrix calibrated successfully.")
            return True
            
        return False

    def transform_point(self, pixel_x, pixel_y):
        """Transforms a single pixel coordinate to real-world coordinate using H."""
        if self.homography_matrix is None:
            return None
        
        pt = np.array([[[pixel_x, pixel_y]]], dtype=np.float32)
        transformed_pt = cv2.perspectiveTransform(pt, self.homography_matrix)
        return transformed_pt[0][0][0], transformed_pt[0][0][1]

    def _run_loop(self):
        """Main processing loop executed in the background thread."""
        # Initialize detector for new OpenCV versions
        detector = None
        if not hasattr(aruco, 'detectMarkers'):
            detector = aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Detect markers
            # API difference between OpenCV versions
            if detector is None:
                corners, ids, rejected = aruco.detectMarkers(gray, self.aruco_dict, parameters=self.aruco_params)
            else:
                corners, ids, rejected = detector.detectMarkers(gray)

            # Draw detections on frame for debugging
            if ids is not None:
                aruco.drawDetectedMarkers(frame, corners, ids)
                
                # Check for calibration / H-matrix update if we don't have it yet
                # Alternatively, you can always update it to make it robust to camera slight bumps.
                if self.homography_matrix is None:
                    self.calibrate_homography(ids, corners)

                # Process the robot's position if Homography is ready and robot marker is found
                if self.homography_matrix is not None and self.ROBOT_MARKER_ID in ids.flatten():
                    idx = np.where(ids.flatten() == self.ROBOT_MARKER_ID)[0][0]
                    robot_corners = corners[idx][0]
                    
                    # 1. Compute Center (pixel)
                    center_px = np.mean(robot_corners[:, 0])
                    center_py = np.mean(robot_corners[:, 1])
                    
                    # 2. Transform Center to Real-World (x, y)
                    real_coords = self.transform_point(center_px, center_py)
                    
                    if real_coords is not None:
                        real_x, real_y = real_coords
                        
                        # 3. Compute Heading (Theta)
                        # ArUco corners are ordered clockwise starting from top-left (TL, TR, BR, BL)
                        # Vector from bottom centers to top centers gives Forward direction
                        top_mid_x = (robot_corners[0][0] + robot_corners[1][0]) / 2.0
                        top_mid_y = (robot_corners[0][1] + robot_corners[1][1]) / 2.0
                        bot_mid_x = (robot_corners[2][0] + robot_corners[3][0]) / 2.0
                        bot_mid_y = (robot_corners[2][1] + robot_corners[3][1]) / 2.0
                        
                        # Note: Y pixel coordinates are flipped (top is 0)
                        # So dy = -(top_y - bot_y) in pixel space, or just use world transform.
                        # For rigorous geometric angle, transform both midpoints to world coordinates:
                        pt_top_world = self.transform_point(top_mid_x, top_mid_y)
                        pt_bot_world = self.transform_point(bot_mid_x, bot_mid_y)
                        
                        if pt_top_world and pt_bot_world:
                            dx = pt_top_world[0] - pt_bot_world[0]
                            dy = pt_top_world[1] - pt_bot_world[1]
                            theta = math.atan2(dy, dx)
                            
                            # Simple low-pass filter (Alpha Filter) for smoothing
                            # Alpha = 0.5
                            with self.lock:
                                if not self._has_valid_pose:
                                    self._current_x = real_x
                                    self._current_y = real_y
                                    self._current_theta = theta
                                    self._has_valid_pose = True
                                else:
                                    self._current_x = 0.5 * real_x + 0.5 * self._current_x
                                    self._current_y = 0.5 * real_y + 0.5 * self._current_y
                                    
                                    # Angle wrap aware smoothing
                                    angle_diff = theta - self._current_theta
                                    if angle_diff > math.pi: angle_diff -= 2 * math.pi
                                    if angle_diff < -math.pi: angle_diff += 2 * math.pi
                                    self._current_theta += 0.5 * angle_diff
                        
            else:
                # If marker completely lost, you might want to flag it or rely on old coords
                # For now, just keep old pose but you could set _has_valid_pose = False
                pass

            # Store the annotated frame for the main thread to show
            self.latest_frame = frame

            # Sleep slightly to prevent 100% CPU on fast cameras
            time.sleep(0.02)


# ======================================================================
# Standalone Testing Block
# ======================================================================
if __name__ == "__main__":
    locator = ArucoLocalization(camera_id=0)
    
    # You can customize anchors if you want
    locator.ANCHOR_IDS = {
        0: (0.0, 0.0),    # Top Left is ID 0
        1: (2.0, 0.0),    # Top Right is ID 1 (2 meters away)
        2: (2.0, 2.0),    # Bot Right ID 2
        3: (0.0, 2.0)     # Bot Left ID 3
    }
    locator.ROBOT_MARKER_ID = 10
    
    if locator.start():
        try:
            while True:
                # 1. Get real-world pose
                # x, y, theta, valid = locator.get_pose()
                # print(f"Robot: x={x:.2f}m, y={y:.2f}m, th={math.degrees(theta):.1f}°, valid={valid}")

                # 2. Show the camera feed
                if locator.latest_frame is not None:
                    cv2.imshow("ArUco Tracking", locator.latest_frame)
                    
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                        
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            locator.stop()
