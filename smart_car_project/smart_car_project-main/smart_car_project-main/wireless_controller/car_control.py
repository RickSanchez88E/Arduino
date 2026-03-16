"""
FYP Ground Control Station -- Robot Navigation Monitor
Telemetry protocol: {T:posX,posY,theta,angleErr,target_v,target_w,goalX,goalY}
Command protocol:   {GOAL:x,y}  |  {ZERO}  |  {SPIN}  |  {Heartbeat}
Cal response:       {CAL:actual_rad}
"""

import tkinter as tk
from tkinter import messagebox
import socket
import threading
import time
import math
import os
import sys

# Import ArUco tracker from same directory
try:
    from aruco_tracker import ArucoLocalization
    ARUCO_AVAILABLE = True
except ImportError:
    ARUCO_AVAILABLE = False


ROBOT_IP     = "192.168.4.1"
ROBOT_PORT   = 100
WHEEL_BASE_M = 0.18   # must match Arduino WHEEL_BASE (m)

# ── Colour palette (Catppuccin Mocha) ──────────────────────────
BG     = "#1e1e2e"   # main background
PANEL  = "#181825"   # sidebar
CARD   = "#313244"   # card / entry bg
BORDER = "#45475a"   # dividers
TXT    = "#cdd6f4"   # primary text
MUTED  = "#6c7086"   # secondary text
BLUE   = "#89b4fa"
GREEN  = "#a6e3a1"
RED    = "#f38ba8"
ORANGE = "#fab387"
PURPLE = "#cba6f7"
YELLOW = "#f9e2af"
TEAL   = "#94e2d5"
# Coordinate source options
SRC_ENCODER = "Encoder"
SRC_VISION  = "Vision"
SRC_FUSED   = "Fused"
# ----------------------------------------------------------------


def _btn(parent, text, cmd, color=BLUE):
    """
    Label-based clickable button.
    On macOS, tk.Button ignores bg/fg due to the Aqua theme.
    Labels always respect colour settings — used as buttons instead.
    """
    def on_enter(_): lbl.config(bg=color, fg=PANEL)
    def on_leave(_): lbl.config(bg=CARD,  fg=color)

    frame = tk.Frame(parent, bg=color, padx=1, pady=1)
    lbl = tk.Label(frame, text=text, bg=CARD, fg=color,
                   font=("Arial", 10, "bold"),
                   padx=10, pady=6, cursor="hand2")
    lbl.pack(fill=tk.X)
    lbl.bind("<Button-1>", lambda _: cmd())
    lbl.bind("<Enter>",    on_enter)
    lbl.bind("<Leave>",    on_leave)
    frame.bind("<Button-1>", lambda _: cmd())
    return frame


def _section(parent, title):
    """Muted section header + divider line."""
    tk.Label(parent, text=f"  {title}", bg=PANEL, fg=MUTED,
             font=("Arial", 8, "bold"), anchor="w").pack(
        fill=tk.X, pady=(14, 2), padx=4)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill=tk.X, padx=8)


class RobotGCS:
    def __init__(self, root):
        self.root = root
        self.root.title("FYP Ground Control Station")
        self.root.configure(bg=BG)
        self.root.geometry("1060x700")

        self.sock         = None
        self.is_connected = False
        self._recv_buf    = ""

        self.curr_theta = 0.0
        self.angle_err  = 0.0

        # -- Vision system state --
        self.vision_tracker = None
        self.vision_enabled = False
        self.coord_source   = SRC_ENCODER
        self.vision_x = 0.0
        self.vision_y = 0.0
        self.vision_theta = 0.0
        self.vision_valid = False

        self._build_ui()
        self.root.after(50, self._compass_tick)
        self.root.after(200, self._vision_poll)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── Left sidebar ─────────────────────────────────────────
        sidebar = tk.Frame(self.root, bg=PANEL, width=268)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0), pady=4)
        sidebar.pack_propagate(False)

        # App title
        tk.Label(sidebar, text="ROBOT GCS", bg=PANEL, fg=TXT,
                 font=("Arial", 14, "bold")).pack(pady=(14, 1))
        tk.Label(sidebar, text="Elegoo Smart Car V4.0", bg=PANEL, fg=MUTED,
                 font=("Arial", 9)).pack()

        # Connection status + button
        self.status_label = tk.Label(sidebar, text="● DISCONNECTED",
                                     fg=RED, font=("Arial", 10, "bold"), bg=PANEL)
        self.status_label.pack(pady=6)
        _btn(sidebar, "⚡  CONNECT", self.connect, color=BLUE).pack(
            fill=tk.X, padx=16, pady=2)

        # ── Compass ──────────────────────────────────────────────
        _section(sidebar, "HEADING MONITOR")

        compass_wrap = tk.Frame(sidebar, bg=CARD, bd=0,
                                highlightbackground=BORDER, highlightthickness=1)
        compass_wrap.pack(padx=16, pady=8)
        self.compass = tk.Canvas(compass_wrap, width=204, height=204,
                                 bg=CARD, highlightthickness=0)
        self.compass.pack()
        self._init_compass()

        row = tk.Frame(sidebar, bg=PANEL)
        row.pack(fill=tk.X, padx=16, pady=(0, 4))
        self.lbl_yaw = tk.Label(row, text="Yaw    0.0°",
                                bg=PANEL, fg=BLUE,
                                font=("Courier", 10, "bold"), anchor="w")
        self.lbl_yaw.pack(side=tk.LEFT)
        self.lbl_err = tk.Label(row, text="Err  0.0°",
                                bg=PANEL, fg=RED,
                                font=("Courier", 10, "bold"), anchor="e")
        self.lbl_err.pack(side=tk.RIGHT)

        _btn(sidebar, "↺  SET CURRENT AS ZERO", self.zero_heading,
             color=ORANGE).pack(fill=tk.X, padx=16, pady=6)

        # ── Goal ─────────────────────────────────────────────────
        _section(sidebar, "GOAL SETTING (m)")

        grid = tk.Frame(sidebar, bg=PANEL)
        grid.pack(fill=tk.X, padx=16, pady=6)

        tk.Label(grid, text="X (m)", bg=PANEL, fg=MUTED,
                 font=("Arial", 9)).grid(row=0, column=0, padx=6, sticky="w")
        self.ent_x = tk.Entry(grid, width=10, justify="center",
                              bg=CARD, fg=TXT, insertbackground=TXT,
                              relief="flat", font=("Courier", 11),
                              highlightbackground=BORDER, highlightthickness=1)
        self.ent_x.insert(0, "0.5")
        self.ent_x.grid(row=1, column=0, padx=6, pady=2)

        tk.Label(grid, text="Y (m)", bg=PANEL, fg=MUTED,
                 font=("Arial", 9)).grid(row=0, column=1, padx=6, sticky="w")
        self.ent_y = tk.Entry(grid, width=10, justify="center",
                              bg=CARD, fg=TXT, insertbackground=TXT,
                              relief="flat", font=("Courier", 11),
                              highlightbackground=BORDER, highlightthickness=1)
        self.ent_y.insert(0, "0.0")
        self.ent_y.grid(row=1, column=1, padx=6, pady=2)

        _btn(sidebar, "▶  SEND GOAL", self.set_goal, color=GREEN).pack(
            fill=tk.X, padx=16, pady=(2, 1))
        _btn(sidebar, "■  STOP (hold position)", self.stop_robot, color=RED).pack(
            fill=tk.X, padx=16, pady=1)

        # -- Vision System ----------------------------------------
        _section(sidebar, "VISION SYSTEM")

        vision_row = tk.Frame(sidebar, bg=PANEL)
        vision_row.pack(fill=tk.X, padx=16, pady=4)

        self.btn_vision = _btn(vision_row, "EYE  VISION OFF",
                               self.toggle_vision, color=MUTED)
        self.btn_vision.pack(fill=tk.X)

        # Coordinate source selector
        src_row = tk.Frame(sidebar, bg=PANEL)
        src_row.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(src_row, text="Source:", bg=PANEL, fg=MUTED,
                 font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 6))
        self.coord_var = tk.StringVar(value=SRC_ENCODER)
        for src in (SRC_ENCODER, SRC_VISION, SRC_FUSED):
            rb = tk.Radiobutton(src_row, text=src, variable=self.coord_var,
                                value=src, bg=PANEL, fg=TXT,
                                selectcolor=CARD, activebackground=PANEL,
                                font=("Arial", 8),
                                command=self._on_source_change)
            rb.pack(side=tk.LEFT, padx=2)

        self.vision_status = tk.Label(
            sidebar, text="Vision: offline",
            font=("Courier", 9), bg=PANEL, fg=MUTED,
            justify=tk.LEFT, wraplength=230, anchor="w")
        self.vision_status.pack(fill=tk.X, padx=20, pady=2)

        # -- Calibration ------------------------------------------
        _section(sidebar, "WHEELBASE CALIBRATION")

        _btn(sidebar, "SPIN  START SPIN CAL", self.start_spin_cal,
             color=PURPLE).pack(fill=tk.X, padx=16, pady=8)

        self.cal_status = tk.Label(
            sidebar, text="Status: idle",
            font=("Courier", 9), bg=PANEL, fg=MUTED,
            justify=tk.LEFT, wraplength=230, anchor="w")
        self.cal_status.pack(fill=tk.X, padx=20)

        # ── Telemetry readout ────────────────────────────────────
        _section(sidebar, "TELEMETRY")

        self.telem_label = tk.Label(
            sidebar,
            text="v:  -.---  m/s   w:  -.--  r/s\nErr:  -.-°   Goal: (-.-- , -.--)",
            font=("Courier", 9), bg=PANEL, fg=TXT,
            justify=tk.LEFT, anchor="w")
        self.telem_label.pack(fill=tk.X, padx=16, pady=6)

        # ── Right panel: map ─────────────────────────────────────
        right = tk.Frame(self.root, bg=BG)
        right.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH, padx=4, pady=4)

        tk.Label(right, text="POSITION MAP", bg=BG, fg=MUTED,
                 font=("Arial", 9, "bold"), anchor="w").pack(
            fill=tk.X, padx=4, pady=(2, 0))

        self.canvas = tk.Canvas(right, bg=CARD,
                                highlightbackground=BORDER, highlightthickness=1)
        self.canvas.pack(expand=True, fill=tk.BOTH, padx=4, pady=4)
        self.canvas.bind("<Configure>", self._on_map_resize)

        self.scale = 250
        self.offX  = 400
        self.offY  = 340

    def _on_map_resize(self, event):
        self.offX = event.width  // 2
        self.offY = event.height // 2
        self.canvas.delete("static")
        self._init_map()

    def _init_compass(self):
        cx, cy, r = 102, 102, 86
        self.compass.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 outline=BORDER, width=1)
        # Inner ring
        self.compass.create_oval(cx - r//2, cy - r//2,
                                 cx + r//2, cy + r//2,
                                 outline=BORDER, width=1, dash=(2, 4))
        # Centre dot
        self.compass.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                                 fill=MUTED, outline="")
        # Cardinal labels: N at top = 0 rad in math convention = theta=0 → forward
        for deg, label in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            rad = math.radians(deg - 90)
            self.compass.create_text(
                cx + (r + 10) * math.cos(rad),
                cy + (r + 10) * math.sin(rad),
                text=label, fill=MUTED, font=("Arial", 8, "bold"))

    def _init_map(self):
        ox, oy, s = self.offX, self.offY, self.scale
        # Background grid (every 0.5 m)
        for d in range(-4 * s, 4 * s + 1, s // 2):
            self.canvas.create_line(0, oy + d, 9999, oy + d,
                                    fill=BORDER, tags="static")
            self.canvas.create_line(ox + d, 0, ox + d, 9999,
                                    fill=BORDER, tags="static")
        # Main axes
        self.canvas.create_line(0, oy, 9999, oy,  fill=MUTED,   tags="static")
        self.canvas.create_line(ox, 0, ox, 9999,  fill=MUTED,   tags="static")
        # 1 m boundary
        self.canvas.create_rectangle(ox - s, oy - s, ox + s, oy + s,
                                     outline=YELLOW, dash=(6, 4), tags="static")
        # Axis labels
        self.canvas.create_text(ox + s + 18, oy - 8,
                                text="+X", fill=MUTED,
                                font=("Arial", 9), tags="static")
        self.canvas.create_text(ox + 10, oy - s - 12,
                                text="+Y", fill=MUTED,
                                font=("Arial", 9), tags="static")
        # Distance ticks
        for m in (-1, -0.5, 0.5, 1):
            px = ox + int(m * s)
            self.canvas.create_text(px, oy + 12, text=f"{m:+.1f}m",
                                    fill=MUTED, font=("Arial", 7), tags="static")
            py = oy - int(m * s)
            self.canvas.create_text(ox + 18, py, text=f"{m:+.1f}m",
                                    fill=MUTED, font=("Arial", 7), tags="static")

    # ------------------------------------------------------------------
    # Compass animation — 50 ms tick on main thread
    # ------------------------------------------------------------------

    def _compass_tick(self):
        self.compass.delete("needle")
        cx, cy = 102, 102

        # Blue arrow = current heading (theta=0 → North = up)
        va = self.curr_theta - math.pi / 2
        self.compass.create_line(
            cx, cy,
            cx + 74 * math.cos(va), cy + 74 * math.sin(va),
            fill=BLUE, width=3, arrow=tk.LAST, tags="needle")

        # Red dashed = target heading
        ta = (self.curr_theta + self.angle_err) - math.pi / 2
        self.compass.create_line(
            cx, cy,
            cx + 60 * math.cos(ta), cy + 60 * math.sin(ta),
            fill=RED, dash=(4, 3), tags="needle")

        self.root.after(50, self._compass_tick)

    # ------------------------------------------------------------------
    # Network
    # ------------------------------------------------------------------

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((ROBOT_IP, ROBOT_PORT))
            self.sock.settimeout(None)
            self.is_connected = True
            self.status_label.config(text="● CONNECTED", fg=GREEN)
            threading.Thread(target=self._receive_handler, daemon=True).start()
            threading.Thread(target=self._heartbeat_loop,  daemon=True).start()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))

    def _receive_handler(self):
        sock = self.sock
        if sock is None:
            return
        while self.is_connected:
            try:
                raw = sock.recv(4096)
                if not raw:
                    raise ConnectionError("socket closed")
                self._recv_buf += raw.decode("utf-8", errors="replace")
                while True:
                    start = self._recv_buf.find("{")
                    if start == -1:
                        self._recv_buf = ""
                        break
                    end = self._recv_buf.find("}", start)
                    if end == -1:
                        self._recv_buf = self._recv_buf[start:]
                        break
                    frame = self._recv_buf[start: end + 1]
                    self._recv_buf = self._recv_buf[end + 1:]
                    self._dispatch_frame(frame)
            except Exception:
                self.is_connected = False
                self.root.after(0, lambda: self.status_label.config(
                    text="● DISCONNECTED", fg=RED))
                break

    def _dispatch_frame(self, frame: str):
        """Route a complete {...} frame. Never touches tkinter directly."""
        try:
            if frame.startswith("{T:"):
                parts = [float(v) for v in frame[3:-1].split(",")]
                if len(parts) == 8:
                    self.root.after(0, self._update_ui, parts)
            elif frame.startswith("{CAL:"):
                actual_rad = float(frame[5:-1])
                self.root.after(0, self._on_cal_result, actual_rad)
        except (ValueError, IndexError):
            pass

    def _heartbeat_loop(self):
        while self.is_connected:
            self._send_cmd("{Heartbeat}")
            time.sleep(1.0)

    def _send_cmd(self, cmd: str):
        if self.is_connected and self.sock:
            try:
                self.sock.sendall(cmd.encode("utf-8"))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def zero_heading(self):
        self._send_cmd("{ZERO}")
        self.canvas.delete("traj")

    def set_goal(self):
        try:
            x = float(self.ent_x.get())
            y = float(self.ent_y.get())
            if abs(x) > 1.2 or abs(y) > 1.2:
                messagebox.showwarning("Range Warning",
                                       "Target is quite far from origin (>1.2 m).")
            self._send_cmd(f"{{GOAL:{x},{y}}}")
        except ValueError:
            messagebox.showerror("Error", "Invalid input — enter numbers only.")

    def stop_robot(self):
        self._send_cmd("{GOAL:0.0,0.0}")

    def start_spin_cal(self):
        if not self.is_connected:
            messagebox.showerror("Not Connected", "Connect to robot first.")
            return
        self.cal_status.config(text="Status: spinning…\n(robot rotating CCW)")
        self._send_cmd("{SPIN}")

    # ------------------------------------------------------------------
    # Calibration result — always called on main thread via root.after()
    # ------------------------------------------------------------------

    def _on_cal_result(self, actual_rad: float):
        actual_deg = math.degrees(actual_rad)
        if actual_rad < math.pi / 2 or actual_rad > 3.0 * math.pi:
            self.cal_status.config(text="Cal FAILED!\nUnexpected angle")
            messagebox.showerror(
                "Calibration Failed",
                f"Magnetometer measured {actual_deg:.1f}° — outside expected range.\n\n"
                "Expected: 180°–540° (roughly one full turn).\n\n"
                "Possible causes:\n"
                "  • Strong magnetic interference nearby\n"
                "  • Robot tipped or moved during spin\n"
                "  • ZERO not pressed before calibrating\n\n"
                "Move to a different location and retry.")
            return

        factor = (2.0 * math.pi) / actual_rad
        new_wb = WHEEL_BASE_M * factor

        self.cal_status.config(
            text=f"Done!  Actual: {actual_deg:.1f}°\nNew WB: {new_wb:.4f} m")

        messagebox.showinfo(
            "Calibration Complete",
            f"Encoder commanded:   360.0°\n"
            f"Magnetometer actual: {actual_deg:.1f}°\n"
            f"Correction factor:   {factor:.4f}\n"
            f"New WHEEL_BASE:      {new_wb:.4f} m\n\n"
            f"Update Arduino firmware:\n"
            f"  const float WHEEL_BASE = {new_wb:.4f}f;\n\n"
            f"Tip: run 2–3 times and average for best accuracy.")

    # ------------------------------------------------------------------
    # UI Update — always called on main thread via root.after()
    # ------------------------------------------------------------------

    def _update_ui(self, p):
        x, y, theta, err, v, w, gx, gy = p

        self.curr_theta = theta
        self.angle_err  = err

        self.lbl_yaw.config(text=f"Yaw  {math.degrees(theta):+7.1f}°")
        self.lbl_err.config(text=f"Err  {math.degrees(err):+7.1f}°")

        self.telem_label.config(
            text=(f"v:  {v:+.3f} m/s   w:  {w:+.2f}  r/s\n"
                  f"Err: {math.degrees(err):+.1f}°"
                  f"   Goal: ({gx:.2f}, {gy:.2f})"))

        # World → canvas
        cx = self.offX + x * self.scale
        cy = self.offY - y * self.scale

        # Trajectory dot
        self.canvas.create_oval(cx - 1.5, cy - 1.5, cx + 1.5, cy + 1.5,
                                fill=BLUE, outline="", tags="traj")

        # Goal marker (crosshair + circle)
        self.canvas.delete("goal_mark")
        gx_p = self.offX + gx * self.scale
        gy_p = self.offY - gy * self.scale
        self.canvas.create_oval(gx_p - 7, gy_p - 7, gx_p + 7, gy_p + 7,
                                outline=RED, width=2, tags="goal_mark")
        self.canvas.create_line(gx_p - 6, gy_p, gx_p + 6, gy_p,
                                fill=RED, tags="goal_mark")
        self.canvas.create_line(gx_p, gy_p - 6, gx_p, gy_p + 6,
                                fill=RED, tags="goal_mark")

        # Robot heading arrow
        self.canvas.delete("robot_arrow")
        a = 22
        ax = cx + a * math.cos(theta)
        ay = cy - a * math.sin(theta)
        self.canvas.create_line(cx, cy, ax, ay,
                                fill=GREEN, width=2, arrow=tk.LAST,
                                tags="robot_arrow")

        # Draw vision pose if available (purple overlay)
        if self.vision_enabled and self.vision_valid:
            vx_p = self.offX + self.vision_x * self.scale
            vy_p = self.offY - self.vision_y * self.scale
            self.canvas.create_oval(vx_p - 2, vy_p - 2, vx_p + 2, vy_p + 2,
                                    fill=PURPLE, outline="", tags="vision_traj")
            # Vision heading arrow (purple)
            self.canvas.delete("vision_arrow")
            va = 22
            vax = vx_p + va * math.cos(self.vision_theta)
            vay = vy_p - va * math.sin(self.vision_theta)
            self.canvas.create_line(vx_p, vy_p, vax, vay,
                                    fill=PURPLE, width=2, arrow=tk.LAST,
                                    tags="vision_arrow")


    # ------------------------------------------------------------------
    # Vision System
    # ------------------------------------------------------------------

    def toggle_vision(self):
        """Toggle ArUco vision system on/off."""
        if not ARUCO_AVAILABLE:
            messagebox.showerror("Vision Unavailable",
                "ArUco tracker module not found.\n\n"
                "Make sure aruco_tracker.py is in the same directory\n"
                "and opencv-contrib-python is installed.")
            return

        if self.vision_enabled:
            # Turn off
            self.vision_enabled = False
            if self.vision_tracker:
                self.vision_tracker.stop()
                self.vision_tracker = None
            self.btn_vision.winfo_children()[0].config(
                text="EYE  VISION OFF", fg=MUTED)
            self.btn_vision.config(bg=MUTED)
            self.vision_status.config(text="Vision: offline", fg=MUTED)
            self.canvas.delete("vision_traj")
            self.canvas.delete("vision_arrow")
        else:
            # Turn on
            try:
                self.vision_tracker = ArucoLocalization(camera_id=0)
                if not self.vision_tracker.start():
                    messagebox.showerror("Vision Error",
                        "Cannot open camera.\n\n"
                        "Check camera permissions and availability.")
                    self.vision_tracker = None
                    return
                self.vision_enabled = True
                self.btn_vision.winfo_children()[0].config(
                    text="EYE  VISION ON", fg=GREEN)
                self.btn_vision.config(bg=GREEN)
                self.vision_status.config(text="Vision: starting...", fg=YELLOW)
            except Exception as e:
                messagebox.showerror("Vision Error", str(e))

    def _on_source_change(self):
        """Handle coordinate source radio button change."""
        self.coord_source = self.coord_var.get()

    def _vision_poll(self):
        """Poll vision system for pose updates (runs on main thread)."""
        if self.vision_enabled and self.vision_tracker:
            x, y, theta, valid = self.vision_tracker.get_pose()
            self.vision_x = x
            self.vision_y = y
            self.vision_theta = theta
            self.vision_valid = valid

            status = self.vision_tracker.get_status()
            cal = "CAL" if status.get('calibrated', False) else "NO CAL"
            fps = status.get('fps', 0)
            anchors = sum(1 for v in status.get('anchors', {}).values() if v)
            pose_str = ""
            if valid:
                pose_str = f"\n  x={x:.3f} y={y:.3f} th={math.degrees(theta):.0f}deg"

            self.vision_status.config(
                text=f"Vision: {cal} | {fps:.0f} FPS | {anchors}/4 anchors{pose_str}",
                fg=GREEN if valid else ORANGE)

        self.root.after(100, self._vision_poll)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = RobotGCS(root)
    root.mainloop()
