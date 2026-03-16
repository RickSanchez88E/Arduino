"""
iPhone to Mac ArUco Detection (HTTP POST)
==========================================
Uses HTTP POST instead of WebSocket for frame streaming stability.
Detection results are visible on both iPhone and Mac.

Usage: python iphone_camera.py
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
import subprocess
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8888

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except: return "127.0.0.1"
    finally: s.close()

LOCAL_IP = get_local_ip()
CERT = "/tmp/ipcam_cert.pem"
KEY  = "/tmp/ipcam_key.pem"

def ensure_cert():
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", KEY, "-out", CERT, "-days", "30", "-nodes",
        "-subj", f"/CN={LOCAL_IP}",
        "-addext", f"subjectAltName=IP:{LOCAL_IP}"
    ], capture_output=True)

# -- Shared state (thread-safe) -----------------------------------
state_lock = threading.Lock()
frame_lock = threading.Lock()
latest_jpeg = None
detection_result = json.dumps({"markers": [], "calibrated": False})
latest_cv_frame = None

# -- ArUco setup --------------------------------------------------
aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
aruco_params = aruco.DetectorParameters() if hasattr(aruco, 'DetectorParameters') else aruco.DetectorParameters_create()
aruco_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
aruco_detector = aruco.ArucoDetector(aruco_dict, aruco_params) if hasattr(aruco, 'ArucoDetector') else None

ANCHORS = {0:(0,0), 1:(1,0), 2:(1,1), 3:(0,1)}
ROBOT_ID = 10
H_matrix = None
detected_ever = set()

def process_frame(jpeg_bytes):
    """Process a JPEG frame with ArUco detection. Updates shared state."""
    global H_matrix, detection_result, detected_ever, latest_cv_frame

    arr = np.frombuffer(jpeg_bytes, np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if aruco_detector:
        corners, ids, _ = aruco_detector.detectMarkers(gray)
    else:
        corners, ids, _ = aruco.detectMarkers(gray, aruco_dict, parameters=aruco_params)

    result = {"markers": [], "calibrated": H_matrix is not None, "robot": None}

    if ids is not None and len(ids) > 0:
        idf = ids.flatten()
        detected_ever.update(idf.tolist())

        for i, mid in enumerate(idf):
            c = corners[i][0]
            cx, cy = float(np.mean(c[:,0])), float(np.mean(c[:,1]))
            # Corners as list for iPhone overlay
            cpts = [[float(c[j][0]), float(c[j][1])] for j in range(4)]
            result["markers"].append({"id": int(mid), "cx": cx, "cy": cy, "corners": cpts})

        # Calibrate
        if all(a in idf for a in ANCHORS):
            sp, dp = [], []
            for a,(rx,ry) in ANCHORS.items():
                idx = np.where(idf==a)[0][0]
                mc = corners[idx][0]
                sp.append([float(np.mean(mc[:,0])), float(np.mean(mc[:,1]))])
                dp.append([rx, ry])
            H_matrix, _ = cv2.findHomography(np.array(sp,np.float32), np.array(dp,np.float32), cv2.RANSAC, 5.0)
            result["calibrated"] = True

        # Robot pose
        if H_matrix is not None and ROBOT_ID in idf:
            idx = np.where(idf==ROBOT_ID)[0][0]
            rc = corners[idx][0]
            rcx, rcy = float(np.mean(rc[:,0])), float(np.mean(rc[:,1]))
            w = cv2.perspectiveTransform(np.array([[[rcx,rcy]]],np.float32), H_matrix)
            wx, wy = float(w[0][0][0]), float(w[0][0][1])
            tm=(rc[0]+rc[1])/2; bm=(rc[2]+rc[3])/2
            pt = cv2.perspectiveTransform(np.array([[[float(tm[0]),float(tm[1])]]],np.float32), H_matrix)
            pb = cv2.perspectiveTransform(np.array([[[float(bm[0]),float(bm[1])]]],np.float32), H_matrix)
            th = math.atan2(float(pt[0][0][1]-pb[0][0][1]), float(pt[0][0][0]-pb[0][0][0]))
            result["robot"] = {"x": round(wx,3), "y": round(wy,3), "theta": round(math.degrees(th),1)}

    with state_lock:
        detection_result = json.dumps(result)

    # Also show on Mac with OpenCV
    fh, fw = frame.shape[:2]
    if ids is not None and len(ids) > 0:
        aruco.drawDetectedMarkers(frame, corners, ids)
        for m in result["markers"]:
            cv2.putText(frame, f"ID:{m['id']}", (int(m['cx'])+10, int(m['cy'])-8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,200,0), 2)

    cv2.rectangle(frame, (0,0), (fw,32), (30,30,30), -1)
    status = "CALIBRATED" if result["calibrated"] else "Waiting anchors"
    cv2.putText(frame, f"iPhone Feed | {status}", (10,22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,200,0) if result["calibrated"] else (0,100,255), 1)

    if result["robot"]:
        r = result["robot"]
        cv2.rectangle(frame, (0,fh-40), (fw,fh), (0,80,0), -1)
        cv2.putText(frame, f"ROBOT x={r['x']:.3f}m y={r['y']:.3f}m th={r['theta']:.1f}deg",
                    (10,fh-12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)

    with frame_lock:
        latest_cv_frame = frame

# -- HTML ---------------------------------------------------------────────
HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>ArUco Camera</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#111;color:#fff;font-family:-apple-system,sans-serif;overflow:hidden}
#wrap{position:relative;width:100vw;height:100vh}
video{width:100%;height:100%;object-fit:cover}
canvas{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none}
#hud{position:fixed;top:0;left:0;right:0;padding:10px 14px;z-index:10;
font-size:14px;font-weight:600;text-align:center}
.ok{background:rgba(26,92,42,0.9)}.no{background:rgba(139,26,26,0.9)}
.wait{background:rgba(92,74,26,0.9)}
#pose{position:fixed;bottom:0;left:0;right:0;padding:12px;
background:rgba(0,100,0,0.9);font-size:16px;font-weight:700;text-align:center;display:none}
#btn{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
padding:22px 55px;font-size:24px;font-weight:700;background:#0a84ff;
color:#fff;border:none;border-radius:16px;z-index:20}
#btn:active{background:#0066cc;transform:translate(-50%,-50%) scale(.97)}
#stats{position:fixed;bottom:50px;right:10px;font-size:11px;color:#888;z-index:5}
</style>
</head>
<body>
<div id="wrap">
<video id="v" autoplay playsinline muted></video>
<canvas id="overlay"></canvas>
</div>
<div id="hud" class="no">Tap START</div>
<div id="pose"></div>
<button id="btn" onclick="go()">START CAMERA</button>
<div id="stats"></div>
<script>
const v=document.getElementById("v"), oc=document.getElementById("overlay"),
ox=oc.getContext("2d"), hud=document.getElementById("hud"),
pose=document.getElementById("pose"), btn=document.getElementById("btn"),
stats=document.getElementById("stats");
const sc=document.createElement("canvas"), sx=sc.getContext("2d");
let sending=false, fc=0, lt=Date.now();

async function go(){
btn.style.display="none";
hud.textContent="Opening camera...";hud.className="wait";
try{
const stream=await navigator.mediaDevices.getUserMedia({
video:{facingMode:{ideal:"environment"},width:{ideal:1920},height:{ideal:1080}},audio:false});
v.srcObject=stream; await v.play();
sc.width=800; sc.height=Math.round(800*v.videoHeight/v.videoWidth);
// Match overlay to video display size
function resizeOverlay(){oc.width=v.clientWidth;oc.height=v.clientHeight}
resizeOverlay(); window.addEventListener("resize",resizeOverlay);
hud.textContent="STREAMING";hud.className="ok";
sending=true; sendLoop();
}catch(e){hud.textContent="Error: "+e.message;hud.className="no";btn.style.display="block"}
}

async function sendLoop(){
if(!sending)return;
sx.drawImage(v,0,0,sc.width,sc.height);
sc.toBlob(async blob=>{
if(!blob){setTimeout(sendLoop,100);return}
try{
const resp=await fetch("/frame",{method:"POST",body:blob,
headers:{"Content-Type":"image/jpeg"}});
const data=await resp.json();
drawOverlay(data);
fc++;
const now=Date.now();
if(now-lt>=1000){stats.textContent=Math.round(fc/((now-lt)/1000))+" FPS";fc=0;lt=now}
}catch(e){}
setTimeout(sendLoop,80);
},"image/jpeg",0.75);
}

function drawOverlay(data){
ox.clearRect(0,0,oc.width,oc.height);
const scaleX=oc.width/sc.width, scaleY=oc.height/sc.height;

if(data.markers&&data.markers.length>0){
hud.textContent="Detected: "+data.markers.map(m=>"ID "+m.id).join(", ");
hud.className="ok";

data.markers.forEach(m=>{
const pts=m.corners;
// Draw green border around marker
ox.strokeStyle="#00ff66"; ox.lineWidth=3;
ox.beginPath();
ox.moveTo(pts[0][0]*scaleX, pts[0][1]*scaleY);
for(let i=1;i<4;i++) ox.lineTo(pts[i][0]*scaleX, pts[i][1]*scaleY);
ox.closePath(); ox.stroke();

// Center dot
ox.fillStyle="#ff0000";
ox.beginPath(); ox.arc(m.cx*scaleX, m.cy*scaleY, 5, 0, Math.PI*2); ox.fill();

// ID label
ox.fillStyle="#ffcc00"; ox.font="bold 18px -apple-system";
ox.fillText("ID:"+m.id, m.cx*scaleX+12, m.cy*scaleY-10);
});
}else{
hud.textContent="No markers - point camera at ArUco tag";
hud.className="no";
}

if(data.calibrated){
hud.textContent+=" | CALIBRATED";
}

if(data.robot){
pose.style.display="block";
pose.textContent="ROBOT x="+data.robot.x+"m y="+data.robot.y+"m heading="+data.robot.theta+"\\u00B0";
}else{
pose.style.display="none";
}
}
</script>
</body>
</html>'''

# -- HTTP Handler -------------------------------------------------────
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def do_POST(self):
        if self.path == "/frame":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            # Process with ArUco
            process_frame(body)

            # Return detection result (thread-safe read)
            with state_lock:
                result_json = detection_result
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(result_json.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass

# -- Main ---------------------------------------------------------────────
def main():
    print("=" * 50)
    print("  iPhone Camera + ArUco Detection")
    print("=" * 50)
    print()

    ensure_cert()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    print(f"  iPhone Safari open:")
    print(f"  https://{LOCAL_IP}:{PORT}")
    print()
    print("  Trust cert -> START CAMERA")
    print("  Detection results show on BOTH iPhone and Mac")
    print()
    print("  Mac window: press q to quit")
    print()

    # Mac display loop
    wait = np.zeros((480, 720, 3), np.uint8)
    cv2.putText(wait, "Waiting for iPhone...", (130, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100,100,100), 2)
    cv2.putText(wait, f"https://{LOCAL_IP}:{PORT}", (130, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0,255,100), 2)

    while True:
        with frame_lock:
            frame = latest_cv_frame
        if frame is not None:
            cv2.imshow("ArUco - iPhone (q=quit)", frame)
        else:
            cv2.imshow("ArUco - iPhone (q=quit)", wait)
        if cv2.waitKey(50) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()
    print("Done.")

if __name__ == "__main__":
    main()
