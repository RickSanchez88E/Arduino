"""
Vision-Guided Navigation Controller
====================================
Combines iPhone camera stream + ArUco localization + WiFi car control.
Mac acts as the brain: sees the car via camera, calculates corrections,
sends velocity commands to Arduino at 10Hz.

Usage:
    python navigator.py                          # Start with defaults
    python navigator.py --target 0.5 0.3         # Go to (0.5, 0.3)m
    python navigator.py --arena 0.8 0.6          # Custom arena size

Architecture:
    iPhone (top-down camera)
      -> Mac (ArUco detection -> pose estimation -> PID controller)
        -> Arduino (velocity execution via {MOVE:v,w})
"""

import ssl
import threading
import socket
import cv2
import cv2.aruco as aruco
import numpy as np
import math
import time
import os
import sys
import json
import argparse
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# Configuration
# ============================================================

# -- Arena (default: 80cm x 60cm, good for home experiments) --
ARENA_WIDTH  = 0.80   # meters (X axis)
ARENA_HEIGHT = 0.60   # meters (Y axis)

# Anchor marker positions (ID -> real-world meters)
# Layout: top-down view
#   ID 0 ─────── ID 1
#    |             |
#    |    arena    |
#    |             |
#   ID 3 ─────── ID 2
ANCHOR_POSITIONS = {
    0: (0.0,         ARENA_HEIGHT),   # top-left
    1: (ARENA_WIDTH, ARENA_HEIGHT),   # top-right
    2: (ARENA_WIDTH, 0.0),            # bottom-right
    3: (0.0,         0.0),            # bottom-left
}

ROBOT_MARKER_ID = 10
VALID_IDS = set(ANCHOR_POSITIONS.keys()) | {ROBOT_MARKER_ID}  # {0,1,2,3,10}

# -- Navigation parameters --
ARRIVE_TOLERANCE   = 0.10   # 10cm - stop when this close to target
HEADING_TOLERANCE  = 0.15   # ~8.6 degrees - acceptable heading error
EXCLUSION_RADIUS   = 0.12   # 12cm - stay this far from anchor markers
MAX_LINEAR_V       = 0.10   # m/s - max forward speed (conservative)
MAX_ANGULAR_W      = 1.5    # rad/s - max turn speed
NAV_LOOP_HZ        = 10     # navigation update rate

# -- PID gains for heading control --
KP_HEADING = 2.0    # Proportional
KD_HEADING = 0.3    # Derivative (damping)

# -- PID gains for distance control --
KP_DISTANCE = 0.8   # Proportional
KI_DISTANCE = 0.05  # Integral (steady-state error)

# -- Car connection --
CAR_IP   = "192.168.4.1"
CAR_PORT = 100

# -- Camera server --
CAMERA_PORT = 8888

# ============================================================
# Utility Functions
# ============================================================

def normalize_angle(a):
    """Normalize angle to [-pi, pi]."""
    return math.atan2(math.sin(a), math.cos(a))

def distance(x1, y1, x2, y2):
    """Euclidean distance between two points."""
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

def clamp_to_safe_zone(tx, ty):
    """If target is inside an exclusion zone, push it to the nearest safe point."""
    for aid, (ax, ay) in ANCHOR_POSITIONS.items():
        d = distance(tx, ty, ax, ay)
        if d < EXCLUSION_RADIUS:
            # Push target outward from the anchor
            if d < 0.001:
                # Exactly on anchor - push toward arena center
                cx, cy = ARENA_WIDTH / 2, ARENA_HEIGHT / 2
                dx, dy = cx - ax, cy - ay
                norm = math.sqrt(dx*dx + dy*dy)
                tx = ax + EXCLUSION_RADIUS * dx / norm
                ty = ay + EXCLUSION_RADIUS * dy / norm
            else:
                dx, dy = tx - ax, ty - ay
                tx = ax + EXCLUSION_RADIUS * dx / d
                ty = ay + EXCLUSION_RADIUS * dy / d
            print(f"[NAV] Target clamped away from anchor {aid} -> ({tx:.3f}, {ty:.3f})m")
    # Also clamp to arena bounds with small margin
    margin = 0.05
    tx = max(margin, min(ARENA_WIDTH - margin, tx))
    ty = max(margin, min(ARENA_HEIGHT - margin, ty))
    return tx, ty


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ============================================================
# Car Connection (WiFi TCP)
# ============================================================

class CarConnection:
    """WiFi TCP connection to the Arduino car."""

    def __init__(self, ip=CAR_IP, port=CAR_PORT):
        self.ip = ip
        self.port = port
        self.sock = None
        self.connected = False
        self._lock = threading.Lock()

    def connect(self):
        """Connect to the car. Returns True on success."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.ip, self.port))
            self.sock.settimeout(0.5)
            self.connected = True
            print(f"[CAR] Connected to {self.ip}:{self.port}")
            return True
        except Exception as e:
            print(f"[CAR] Connection failed: {e}")
            self.connected = False
            return False

    def send(self, cmd):
        """Send a command string to the car."""
        if not self.connected:
            return False
        with self._lock:
            try:
                self.sock.sendall(cmd.encode("utf-8"))
                return True
            except Exception:
                self.connected = False
                return False

    def move(self, v, w):
        """Send velocity command: v=linear (m/s), w=angular (rad/s)."""
        v = max(-MAX_LINEAR_V, min(MAX_LINEAR_V, v))
        w = max(-MAX_ANGULAR_W, min(MAX_ANGULAR_W, w))
        return self.send(f"{{MOVE:{v:.4f},{w:.4f}}}")

    def stop(self):
        """Emergency stop."""
        return self.send("{STOP}")

    def close(self):
        if self.sock:
            try:
                self.send("{STOP}")
                self.sock.close()
            except Exception:
                pass
        self.connected = False


# ============================================================
# Vision System (ArUco + iPhone Camera)
# ============================================================

class VisionSystem:
    """iPhone camera + ArUco detection + homography localization."""

    def __init__(self):
        self.lock = threading.Lock()
        self.robot_x = 0.0
        self.robot_y = 0.0
        self.robot_theta = 0.0
        self.robot_valid = False
        self.calibrated = False
        self.H_matrix = None
        self.anchor_count = 0
        self.fps = 0.0
        self.latest_frame = None  # Annotated frame for display

        # ArUco setup
        self.aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        self.aruco_params = aruco.DetectorParameters() if hasattr(aruco, 'DetectorParameters') else aruco.DetectorParameters_create()
        self.aruco_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.aruco_params.cornerRefinementMaxIterations = 50
        self.aruco_params.minMarkerPerimeterRate = 0.05   # Reject tiny false positives
        self.detector = aruco.ArucoDetector(self.aruco_dict, self.aruco_params) if hasattr(aruco, 'ArucoDetector') else None

        # FPS counter
        self._frame_count = 0
        self._fps_time = time.time()

    def process_frame(self, jpeg_bytes):
        """Process a JPEG frame. Updates robot pose."""
        arr = np.frombuffer(jpeg_bytes, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return json.dumps({"markers": [], "calibrated": False})

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self.detector:
            corners, ids, _ = self.detector.detectMarkers(gray)
        else:
            corners, ids, _ = aruco.detectMarkers(gray, self.aruco_dict,
                                                   parameters=self.aruco_params)

        # FPS
        self._frame_count += 1
        now = time.time()
        if now - self._fps_time >= 1.0:
            self.fps = self._frame_count / (now - self._fps_time)
            self._frame_count = 0
            self._fps_time = now

        result = {"markers": [], "calibrated": False, "robot": None,
                  "arena": {"w": ARENA_WIDTH, "h": ARENA_HEIGHT}}

        if ids is not None and len(ids) > 0:
            # Filter out unknown IDs (reject false positives like ID:37)
            idf = ids.flatten()
            valid_mask = np.isin(idf, list(VALID_IDS))
            if not np.any(valid_mask):
                ids = None
                corners = []
            else:
                ids = ids[valid_mask]
                corners = [corners[i] for i in range(len(valid_mask)) if valid_mask[i]]
                idf = ids.flatten()

            for i, mid in enumerate(idf):
                c = corners[i][0]
                cx, cy = float(np.mean(c[:, 0])), float(np.mean(c[:, 1]))
                cpts = [[float(c[j][0]), float(c[j][1])] for j in range(4)]
                result["markers"].append({"id": int(mid), "cx": cx, "cy": cy, "corners": cpts})

            # Calibrate homography
            visible_anchors = [a for a in ANCHOR_POSITIONS if a in idf]
            self.anchor_count = len(visible_anchors)

            if len(visible_anchors) >= 4:
                sp, dp = [], []
                for a in visible_anchors:
                    rx, ry = ANCHOR_POSITIONS[a]
                    idx = np.where(idf == a)[0][0]
                    mc = corners[idx][0]
                    sp.append([float(np.mean(mc[:, 0])), float(np.mean(mc[:, 1]))])
                    dp.append([rx, ry])
                H, _ = cv2.findHomography(np.array(sp, np.float32),
                                           np.array(dp, np.float32),
                                           cv2.RANSAC, 5.0)
                if H is not None:
                    with self.lock:
                        self.H_matrix = H
                        self.calibrated = True
                    result["calibrated"] = True

            # Robot pose
            with self.lock:
                H = self.H_matrix
                cal = self.calibrated

            if cal and H is not None and ROBOT_MARKER_ID in idf:
                idx = np.where(idf == ROBOT_MARKER_ID)[0][0]
                rc = corners[idx][0]
                rcx, rcy = float(np.mean(rc[:, 0])), float(np.mean(rc[:, 1]))

                # Center -> world coordinates
                w = cv2.perspectiveTransform(
                    np.array([[[rcx, rcy]]], np.float32), H)
                wx, wy = float(w[0][0][0]), float(w[0][0][1])

                # Heading from marker edge geometry
                tm = (rc[0] + rc[1]) / 2  # top midpoint
                bm = (rc[2] + rc[3]) / 2  # bottom midpoint
                pt = cv2.perspectiveTransform(
                    np.array([[[float(tm[0]), float(tm[1])]]], np.float32), H)
                pb = cv2.perspectiveTransform(
                    np.array([[[float(bm[0]), float(bm[1])]]], np.float32), H)
                th = math.atan2(float(pt[0][0][1] - pb[0][0][1]),
                                float(pt[0][0][0] - pb[0][0][0]))

                with self.lock:
                    self.robot_x = wx
                    self.robot_y = wy
                    self.robot_theta = th
                    self.robot_valid = True

                result["robot"] = {"x": round(wx, 3), "y": round(wy, 3),
                                   "theta": round(math.degrees(th), 1)}
            else:
                with self.lock:
                    self.robot_valid = False

        else:
            with self.lock:
                self.robot_valid = False

        # Draw on frame for Mac display
        fh, fw = frame.shape[:2]
        if ids is not None:
            aruco.drawDetectedMarkers(frame, corners, ids)

        # Status bar
        cv2.rectangle(frame, (0, 0), (fw, 36), (30, 30, 30), -1)
        status = "CALIBRATED" if self.calibrated else f"WAITING ({self.anchor_count}/4 anchors)"
        color = (0, 200, 0) if self.calibrated else (0, 100, 255)
        cv2.putText(frame, f"Vision: {status} | {self.fps:.0f} FPS",
                    (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)

        if result.get("robot"):
            r = result["robot"]
            cv2.rectangle(frame, (0, fh - 40), (fw, fh), (0, 80, 0), -1)
            cv2.putText(frame, f"CAR x={r['x']:.3f}m y={r['y']:.3f}m heading={r['theta']:.1f}deg",
                        (10, fh - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        with self.lock:
            self.latest_frame = frame

        return json.dumps(result)

    def get_pose(self):
        """Thread-safe pose getter. Returns (x, y, theta, valid)."""
        with self.lock:
            return self.robot_x, self.robot_y, self.robot_theta, self.robot_valid


# ============================================================
# Navigation Controller
# ============================================================

class Navigator:
    """PID-based navigation controller using vision feedback."""

    def __init__(self, car, vision):
        self.car = car
        self.vision = vision

        self.target_x = ARENA_WIDTH / 2
        self.target_y = ARENA_HEIGHT / 2
        self.has_target = False
        self.navigating = False
        self.arrived = False

        # PID state
        self._last_heading_err = 0.0
        self._dist_integral = 0.0
        self._last_time = time.time()

        # Telemetry
        self.status = "IDLE"
        self.dist_to_target = 0.0

    def set_target(self, x, y):
        """Set a new target coordinate (meters)."""
        x, y = clamp_to_safe_zone(x, y)
        self.target_x = x
        self.target_y = y
        self.has_target = True
        self.navigating = True
        self.arrived = False
        self._dist_integral = 0.0
        self._last_heading_err = 0.0
        self._last_time = time.time()
        self.status = "NAVIGATING"
        print(f"[NAV] Target set: ({x:.3f}, {y:.3f})m")

    def cancel(self):
        """Cancel current navigation."""
        self.navigating = False
        self.has_target = False
        self.status = "CANCELLED"
        if self.car.connected:
            self.car.stop()

    def update(self):
        """Run one navigation update cycle. Call at NAV_LOOP_HZ."""
        if not self.navigating or not self.has_target:
            return

        x, y, theta, valid = self.vision.get_pose()

        if not valid:
            # Lost vision - stop and wait
            self.car.move(0, 0)
            self.status = "LOST_VISION"
            return

        now = time.time()
        dt = now - self._last_time
        self._last_time = now
        if dt < 0.001:
            dt = 0.001

        # Distance to target
        dx = self.target_x - x
        dy = self.target_y - y
        dist = math.sqrt(dx * dx + dy * dy)
        self.dist_to_target = dist

        # Arrived?
        if dist < ARRIVE_TOLERANCE:
            self.car.stop()
            self.navigating = False
            self.arrived = True
            self.status = "ARRIVED"
            print(f"[NAV] ARRIVED at ({x:.3f}, {y:.3f})m, error={dist:.3f}m")
            return

        # Desired heading toward target
        desired_heading = math.atan2(dy, dx)

        # Heading error
        heading_err = normalize_angle(desired_heading - theta)

        # Heading PID (P + D)
        heading_d = (heading_err - self._last_heading_err) / dt
        self._last_heading_err = heading_err

        w = KP_HEADING * heading_err + KD_HEADING * heading_d
        w = max(-MAX_ANGULAR_W, min(MAX_ANGULAR_W, w))

        # Distance PID (P + I) - but reduce speed when heading is off
        heading_factor = max(0.0, math.cos(heading_err))  # 0 when sideways, 1 when aligned
        self._dist_integral = max(-0.5, min(0.5,
            self._dist_integral + dist * dt))

        v = (KP_DISTANCE * dist + KI_DISTANCE * self._dist_integral) * heading_factor
        v = max(0, min(MAX_LINEAR_V, v))

        # If heading error is large, turn in place first
        if abs(heading_err) > 0.5:  # ~28 degrees
            v = 0.0

        self.car.move(v, w)
        self.status = f"NAV d={dist:.2f}m h={math.degrees(heading_err):.0f}deg v={v:.3f} w={w:.2f}"


# ============================================================
# HTTP Server (serves iPhone UI + receives frames)
# ============================================================

# Global references (set in main)
g_vision = None
g_navigator = None

CERT = "/tmp/ipcam_cert.pem"
KEY  = "/tmp/ipcam_key.pem"

def ensure_cert(ip):
    """Generate self-signed cert for HTTPS."""
    if os.path.exists(CERT) and os.path.exists(KEY):
        # Check if cert matches current IP
        try:
            result = subprocess.run(["openssl", "x509", "-in", CERT, "-noout", "-text"],
                                     capture_output=True, text=True)
            if ip in result.stdout:
                return  # Cert is valid for this IP
        except Exception:
            pass
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", KEY, "-out", CERT, "-days", "30", "-nodes",
        "-subj", f"/CN={ip}",
        "-addext", f"subjectAltName=IP:{ip}"
    ], capture_output=True)


# -- Web UI HTML --
def get_html(local_ip):
    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Navigator</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#111;color:#fff;font-family:-apple-system,sans-serif;overflow:hidden;touch-action:none}}
#wrap{{position:relative;width:100vw;height:60vh}}
video{{width:100%;height:100%;object-fit:cover}}
canvas{{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none}}
#hud{{position:fixed;top:0;left:0;right:0;padding:8px 12px;z-index:10;
font-size:13px;font-weight:600;text-align:center}}
.ok{{background:rgba(26,92,42,0.9)}}.no{{background:rgba(139,26,26,0.9)}}
.wait{{background:rgba(92,74,26,0.9)}}
#controls{{padding:12px;background:#1a1a2e}}
#target-inputs{{display:flex;gap:10px;margin:8px 0;align-items:center;justify-content:center}}
#target-inputs label{{font-size:14px;color:#aaa}}
#target-inputs input{{width:70px;padding:8px;font-size:16px;background:#222;color:#fff;
border:1px solid #444;border-radius:8px;text-align:center}}
.btn{{padding:14px 28px;font-size:16px;font-weight:700;border:none;border-radius:12px;
cursor:pointer;margin:5px}}
.btn-start{{background:#0a84ff;color:#fff}}
.btn-stop{{background:#ff3b30;color:#fff}}
.btn-cam{{background:#34c759;color:#fff}}
#nav-status{{padding:8px;font-size:14px;color:#ccc;text-align:center;
background:#1e1e2e;min-height:40px}}
#pose{{padding:8px;font-size:13px;color:#0f0;text-align:center;font-family:monospace}}
#stats{{position:fixed;bottom:4px;right:8px;font-size:11px;color:#555}}
</style>
</head>
<body>
<div id="wrap">
<video id="v" autoplay playsinline muted></video>
<canvas id="overlay"></canvas>
</div>
<div id="hud" class="no">Tap START CAMERA</div>
<div id="controls">
<button id="btn-cam" class="btn btn-cam" onclick="startCam()">START CAMERA</button>
<div id="target-inputs">
<label>X(m):</label><input id="tx" type="number" value="0.40" step="0.05">
<label>Y(m):</label><input id="ty" type="number" value="0.30" step="0.05">
</div>
<div style="text-align:center">
<button class="btn btn-start" onclick="sendTarget()">GO TO TARGET</button>
<button class="btn btn-stop" onclick="sendStop()">STOP</button>
</div>
</div>
<div id="nav-status">Navigation: idle</div>
<div id="pose"></div>
<div id="stats"></div>

<script>
const v=document.getElementById("v"), oc=document.getElementById("overlay"),
ox=oc.getContext("2d"), hud=document.getElementById("hud"),
navStatus=document.getElementById("nav-status"),
poseDiv=document.getElementById("pose"),
stats=document.getElementById("stats");
const sc=document.createElement("canvas"), sx=sc.getContext("2d");
let sending=false, fc=0, lt=Date.now();

async function startCam(){{
document.getElementById("btn-cam").style.display="none";
hud.textContent="Opening camera...";hud.className="wait";
try{{
const stream=await navigator.mediaDevices.getUserMedia({{
video:{{facingMode:{{ideal:"environment"}},width:{{ideal:1920}},height:{{ideal:1080}}}},audio:false}});
v.srcObject=stream; await v.play();
sc.width=480; sc.height=Math.round(480*v.videoHeight/v.videoWidth);
function resizeOverlay(){{oc.width=v.clientWidth;oc.height=v.clientHeight}}
resizeOverlay(); window.addEventListener("resize",resizeOverlay);
hud.textContent="STREAMING";hud.className="ok";
sending=true; sendLoop();
}}catch(e){{hud.textContent="Error: "+e.message;hud.className="no";
document.getElementById("btn-cam").style.display="block"}}
}}

async function sendLoop(){{
if(!sending)return;
sx.drawImage(v,0,0,sc.width,sc.height);
sc.toBlob(async blob=>{{
if(!blob){{setTimeout(sendLoop,100);return}}
try{{
const resp=await fetch("/frame",{{method:"POST",body:blob,
headers:{{"Content-Type":"image/jpeg"}}}});
const data=await resp.json();
drawOverlay(data);
fc++;const now=Date.now();
if(now-lt>=1000){{stats.textContent=Math.round(fc/((now-lt)/1000))+" FPS";fc=0;lt=now}}
}}catch(e){{}}
setTimeout(sendLoop,100);
}},"image/jpeg",0.75);
}}

function drawOverlay(data){{
ox.clearRect(0,0,oc.width,oc.height);
const scX=oc.width/sc.width, scY=oc.height/sc.height;
if(data.markers&&data.markers.length>0){{
hud.textContent="Detected: "+data.markers.map(m=>"ID "+m.id).join(", ");
hud.className="ok";
data.markers.forEach(m=>{{
const pts=m.corners;
ox.strokeStyle="#00ff66";ox.lineWidth=3;
ox.beginPath();
ox.moveTo(pts[0][0]*scX,pts[0][1]*scY);
for(let i=1;i<4;i++) ox.lineTo(pts[i][0]*scX,pts[i][1]*scY);
ox.closePath();ox.stroke();
ox.fillStyle="#ffcc00";ox.font="bold 16px -apple-system";
ox.fillText("ID:"+m.id,m.cx*scX+10,m.cy*scY-8);
}});
}}else{{
hud.textContent="No markers";hud.className="no";
}}
if(data.calibrated)hud.textContent+=" | CALIBRATED";
if(data.robot){{
poseDiv.textContent="CAR x="+data.robot.x+"m y="+data.robot.y+"m heading="+data.robot.theta+"deg";
}}
if(data.nav_status){{
navStatus.textContent="Nav: "+data.nav_status;
navStatus.style.color=data.nav_status.includes("ARRIVED")?"#0f0":
data.nav_status.includes("LOST")?"#f00":"#ccc";
}}
// Draw target crosshair if navigating
if(data.target&&data.calibrated&&data.H_inv){{
// Target will be drawn server-side on the frame
}}
}}

async function sendTarget(){{
const x=parseFloat(document.getElementById("tx").value);
const y=parseFloat(document.getElementById("ty").value);
if(isNaN(x)||isNaN(y))return;
try{{await fetch("/navigate",{{method:"POST",body:JSON.stringify({{x:x,y:y}}),
headers:{{"Content-Type":"application/json"}}}})}}catch(e){{}}
}}

async function sendStop(){{
try{{await fetch("/stop",{{method:"POST"}})}}catch(e){{}}
}}
</script>
</body>
</html>'''


class NavigatorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        local_ip = get_local_ip()
        html = get_html(local_ip)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_POST(self):
        if self.path == "/frame":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            result_json = g_vision.process_frame(body)

            # Inject navigation status
            result = json.loads(result_json)
            if g_navigator:
                result["nav_status"] = g_navigator.status
                if g_navigator.has_target:
                    result["target"] = {"x": g_navigator.target_x, "y": g_navigator.target_y}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        elif self.path == "/navigate":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            x, y = float(body["x"]), float(body["y"])
            if g_navigator:
                g_navigator.set_target(x, y)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        elif self.path == "/stop":
            if g_navigator:
                g_navigator.cancel()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


# ============================================================
# Main
# ============================================================

def main():
    global g_vision, g_navigator, ARENA_WIDTH, ARENA_HEIGHT, ANCHOR_POSITIONS

    parser = argparse.ArgumentParser(description="Vision-Guided Navigation Controller")
    parser.add_argument("--target", nargs=2, type=float, metavar=("X", "Y"),
                        help="Initial target coordinates in meters")
    parser.add_argument("--arena", nargs=2, type=float, metavar=("W", "H"),
                        default=[0.80, 0.60],
                        help="Arena size in meters (default: 0.80 0.60)")
    parser.add_argument("--car-ip", type=str, default=CAR_IP,
                        help=f"Car WiFi IP (default: {CAR_IP})")
    parser.add_argument("--no-car", action="store_true",
                        help="Run without car connection (vision-only mode)")
    args = parser.parse_args()

    # Update arena
    ARENA_WIDTH, ARENA_HEIGHT = args.arena
    ANCHOR_POSITIONS = {
        0: (0.0,         ARENA_HEIGHT),
        1: (ARENA_WIDTH, ARENA_HEIGHT),
        2: (ARENA_WIDTH, 0.0),
        3: (0.0,         0.0),
    }

    local_ip = get_local_ip()

    print("=" * 60)
    print("  Vision-Guided Navigation Controller")
    print("=" * 60)
    print()
    print(f"  Arena: {ARENA_WIDTH}m x {ARENA_HEIGHT}m")
    print(f"  Anchors: {ANCHOR_POSITIONS}")
    print(f"  Robot marker: ID {ROBOT_MARKER_ID}")
    print(f"  Arrive tolerance: {ARRIVE_TOLERANCE*100:.0f}cm")
    print(f"  Exclusion radius: {EXCLUSION_RADIUS*100:.0f}cm")
    print()

    # -- Vision system --
    g_vision = VisionSystem()

    # -- Car connection --
    car = CarConnection(ip=args.car_ip)
    if not args.no_car:
        print(f"[CAR] Connecting to {args.car_ip}:{CAR_PORT}...")
        if not car.connect():
            print("[CAR] WARNING: Cannot connect to car. Running in vision-only mode.")
            print("[CAR] Use --no-car flag to suppress this warning.")
            print()
    else:
        print("[CAR] Vision-only mode (no car connection)")

    # -- Navigator --
    g_navigator = Navigator(car, g_vision)

    if args.target:
        g_navigator.set_target(args.target[0], args.target[1])

    # -- HTTPS server for iPhone --
    ensure_cert(local_ip)
    server = HTTPServer(("0.0.0.0", CAMERA_PORT), NavigatorHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print(f"  iPhone Safari open:")
    print(f"  https://{local_ip}:{CAMERA_PORT}")
    print()
    print("  Trust cert -> START CAMERA -> set target -> GO TO TARGET")
    print()
    print("  Mac window: press q to quit, t to set target, s to stop")
    print()

    # -- Navigation loop (background thread) --
    def nav_loop():
        interval = 1.0 / NAV_LOOP_HZ
        while True:
            g_navigator.update()
            time.sleep(interval)

    nav_thread = threading.Thread(target=nav_loop, daemon=True)
    nav_thread.start()

    # -- Mac display loop (main thread) --
    wait_frame = np.zeros((480, 720, 3), np.uint8)
    cv2.putText(wait_frame, "Waiting for iPhone...", (120, 180),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 100, 100), 2)
    cv2.putText(wait_frame, f"https://{local_ip}:{CAMERA_PORT}", (120, 250),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 100), 2)
    cv2.putText(wait_frame, f"Arena: {ARENA_WIDTH}m x {ARENA_HEIGHT}m", (120, 310),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 180, 180), 1)

    try:
        while True:
            with g_vision.lock:
                frame = g_vision.latest_frame

            if frame is not None:
                display = frame.copy()
                # Draw navigation info on Mac display
                fh, fw = display.shape[:2]

                if g_navigator.has_target and g_vision.calibrated:
                    # Draw target on frame (if homography available)
                    try:
                        H_inv = np.linalg.inv(g_vision.H_matrix)
                        tp = cv2.perspectiveTransform(
                            np.array([[[g_navigator.target_x, g_navigator.target_y]]],
                                      np.float32), H_inv)
                        tpx, tpy = int(tp[0][0][0]), int(tp[0][0][1])
                        # Red crosshair for target
                        cv2.drawMarker(display, (tpx, tpy), (0, 0, 255),
                                       cv2.MARKER_CROSS, 30, 2)
                        cv2.putText(display, "TARGET", (tpx + 15, tpy - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    except Exception:
                        pass

                # Navigation status bar
                nav_text = g_navigator.status
                nav_color = (0, 255, 0) if "ARRIVED" in nav_text else \
                            (0, 0, 255) if "LOST" in nav_text else (255, 200, 0)
                cv2.rectangle(display, (0, fh - 70), (fw, fh - 40), (40, 40, 40), -1)
                cv2.putText(display, nav_text, (10, fh - 48),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, nav_color, 1)

                cv2.imshow("Navigator (q=quit, t=target, s=stop)", display)
            else:
                cv2.imshow("Navigator (q=quit, t=target, s=stop)", wait_frame)

            key = cv2.waitKey(50) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):
                g_navigator.cancel()
                print("[NAV] Stopped.")
            elif key == ord('t'):
                # Quick target from keyboard
                try:
                    tx = float(input("  Target X (m): "))
                    ty = float(input("  Target Y (m): "))
                    g_navigator.set_target(tx, ty)
                except (ValueError, EOFError):
                    print("  Invalid input.")

    except KeyboardInterrupt:
        pass
    finally:
        car.close()
        cv2.destroyAllWindows()
        print("\nShutdown complete.")


if __name__ == "__main__":
    main()
