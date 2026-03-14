/**
 * Elegoo Smart Robot Car V4.0 - Professional Control Stack
 * * Architecture: Cascaded PID Control
 * - Tier 3 (Outer): Position Control (m -> m/s)
 * - Tier 2 (Middle): Heading/Yaw Control (rad -> m/s offset)
 * - Tier 1 (Inner): Dual Independent Velocity Control (m/s -> PWM)
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_ADXL345_U.h>
#include <Adafruit_HMC5883_U.h>

// ============================================================
// 1. CONTROL PARAMETERS (TUNING)
// ============================================================

// --- Outer Loop: Position PID (Determines Forward Velocity) ---
float Kp_pos = 5.0f;
float Ki_pos = 0.02f;

// --- Middle Loop: Heading PID (Magnetometer Feedback) ---
// Note: Kp_yaw/Kd_yaw are negative as sensor orientation is inverted
float Kp_yaw = -0.1f;   
float Ki_yaw = 0.0f;
float Kd_yaw = -0.05f;  // Derivative term for damping oscillations

// --- Inner Loop: Independent Wheel Velocity PID ---
float Kp_vel = 100.0f; 
float Ki_vel = 0.0f;

// --- Physical Constraints & Constants ---
const float MAX_V        = 0.14f;   // Max linear velocity (m/s)
const float MAX_CORR     = 0.06f;   // Max differential correction (m/s)
const float FF_GAIN      = 2200.0f; // Feed-forward: Velocity to PWM mapping
const float MIN_PWM      = 45;      // Minimum PWM to overcome static friction
const float DIST_PER_PULSE = (3.14159f * 0.066f) / 1920.0f; // Wheel Odometry
const float MAG_ALPHA    = 0.5f;    // EMA Filter factor (0.0 to 1.0)

// ============================================================
// 2. HARDWARE & STATE VARIABLES
// ============================================================
Adafruit_ADXL345_Unified accel = Adafruit_ADXL345_Unified(12345);
Adafruit_HMC5883_Unified mag   = Adafruit_HMC5883_Unified(12346);

float posX = 0;            // Integrated X position (meters)
float goalX = 0;           // Target X position (meters)
bool  hasGoal = false;
float yawOffset = 0;       // Initial heading reference
float filteredYaw = 0;     // Low-pass filtered heading (radians)

// PID Accumulators & History
float i_pos = 0;
float i_yaw = 0, lastYawErr = 0;
float i_velL = 0, i_velR = 0;

// Motor State
bool dirL_fwd = true, dirR_fwd = true;
volatile long pulseL = 0, pulseR = 0;
uint8_t last_PINC, last_PIND;

// ============================================================
// 3. SENSOR FUSION: TILT-COMPENSATED MAGNETOMETER
// ============================================================
float getRawHeading() {
  sensors_event_t a, m;
  accel.getEvent(&a); mag.getEvent(&m);

  // Calculate Roll & Pitch for tilt compensation
  float roll  = atan2(a.acceleration.y, a.acceleration.z);
  float pitch = atan2(-a.acceleration.x, sqrt(a.acceleration.y * a.acceleration.y + a.acceleration.z * a.acceleration.z));
  
  // Transform Magnetometer data to horizontal plane
  float Xh = m.magnetic.x * cos(pitch) + m.magnetic.z * sin(pitch);
  float Yh = m.magnetic.x * sin(roll) * sin(pitch) + m.magnetic.y * cos(roll) - m.magnetic.z * sin(roll) * cos(pitch);
  
  return atan2(Yh, Xh);
}

// ============================================================
// 4. TIER 1: VELOCITY PID (ACTUATOR LAYER)
// ============================================================
void executeSpeedPID(float vL_target, float vR_target, float vL_actual, float vR_actual, float dt) {
  float errL = vL_target - vL_actual;
  float errR = vR_target - vR_actual;

  // Velocity Integration with Anti-windup
  i_velL = constrain(i_velL + errL * dt, -60, 60);
  i_velR = constrain(i_velR + errR * dt, -60, 60);

  // Combine Feed-forward (FF) and Feedback (PID)
  float pwmL = (vL_target * FF_GAIN) + (errL * Kp_vel) + (i_velL * Ki_vel);
  float pwmR = (vR_target * FF_GAIN) + (errR * Kp_vel) + (i_velR * Ki_vel);

  // Full stop logic
  if (abs(vL_target) < 0.005 && abs(vR_target) < 0.005) {
    pwmL = 0; pwmR = 0; i_velL = 0; i_velR = 0;
  } else {
    // Apply static friction compensation
    if (abs(pwmL) < MIN_PWM) pwmL = (pwmL > 0) ? MIN_PWM : -MIN_PWM;
    if (abs(pwmR) < MIN_PWM) pwmR = (pwmR > 0) ? MIN_PWM : -MIN_PWM;
  }

  // Update direction and write to hardware
  dirL_fwd = (pwmL >= 0); dirR_fwd = (pwmR >= 0);
  digitalWrite(8, dirL_fwd ? LOW : HIGH);
  digitalWrite(7, dirR_fwd ? LOW : HIGH);
  analogWrite(6, (uint8_t)constrain(abs(pwmL), 0, 255));
  analogWrite(5, (uint8_t)constrain(abs(pwmR), 0, 255));
}

// ============================================================
// 5. SYSTEM INITIALIZATION
// ============================================================
void setup() {
  Serial.begin(9600);
  Wire.begin();
  accel.begin();
  mag.begin();

  pinMode(3, OUTPUT); digitalWrite(3, HIGH); // Standby Pin
  pinMode(8, OUTPUT); pinMode(6, OUTPUT);     // Left Motor
  pinMode(7, OUTPUT); pinMode(5, OUTPUT);     // Right Motor

  // Sensor Warm-up & Calibration (500ms stabilization)
  Serial.println("{INFO:calibrating_mag}");
  delay(500); 
  
  float sumYaw = 0;
  for(int i = 0; i < 20; i++) {
    sumYaw += getRawHeading();
    delay(10);
  }
  yawOffset = sumYaw / 20.0f; // Record power-on heading as zero
  filteredYaw = 0;

  // Pin Change Interrupts for Encoders
  cli();
  PCICR  |= (1 << PCIE1) | (1 << PCIE2);
  PCMSK1 |= (1 << PCINT8) | (1 << PCINT9) | (1 << PCINT10); // A0, A1, A2
  PCMSK2 |= (1 << PCINT20);                                 // D4
  sei();

  Serial.println("{INFO:system_ready}");
}

// ============================================================
// 6. CONTROL LOOP (20Hz / 50ms)
// ============================================================
void loop() {
  // Command Parsing
  while (Serial.available()) {
    static String buf = ""; char ch = Serial.read(); buf += ch;
    if (ch == '}') {
      if (buf.indexOf("GOAL") >= 0) {
        int ci = buf.indexOf(':'), mi = buf.indexOf(',');
        goalX = buf.substring(ci + 1, mi).toFloat();
        hasGoal = true;
        // Reset state for new trajectory
        posX = 0; i_pos = 0; i_yaw = 0; i_velL = 0; i_velR = 0; lastYawErr = 0;
      } else if (buf.indexOf("ZERO") >= 0) {
        posX = 0; goalX = 0; hasGoal = false;
        yawOffset = getRawHeading(); filteredYaw = 0;
        Serial.println("{INFO:zeroed}");
      }
      buf = "";
    }
  }

  // Periodic Execution
  static unsigned long lastMs = 0;
  if (millis() - lastMs < 50) return;
  float dt = (millis() - lastMs) / 1000.0f;
  lastMs = millis();

  // A. Odometry Update
  cli();
  long cL = pulseL; pulseL = 0; long cR = pulseR; pulseR = 0;
  sei();

  float dL = (cL / 1.0f) * DIST_PER_PULSE * (dirL_fwd ? 1 : -1);
  float dR = (cR / 1.0f) * DIST_PER_PULSE * (dirR_fwd ? 1 : -1);
  float vL_act = dL / dt;
  float vR_act = dR / dt;
  posX += (dL + dR) / 2.0f;

  // B. Heading Filtering (Angle Wrap Aware)
  float raw = getRawHeading() - yawOffset;
  float angleDiff = raw - filteredYaw;
  if (angleDiff >  PI) angleDiff -= 2.0f * PI;
  if (angleDiff < -PI) angleDiff += 2.0f * PI;
  filteredYaw += MAG_ALPHA * angleDiff;

  // C. Cascaded Control Logic
  if (!hasGoal) {
    executeSpeedPID(0, 0, vL_act, vR_act, dt);
  } else {
    // Tier 3: Position Control -> Base Velocity
    float posErr = goalX - posX;
    if (abs(posErr) < 0.02f) {
      hasGoal = false;
      executeSpeedPID(0, 0, vL_act, vR_act, dt);
      Serial.println("{INFO:arrived}");
    } else {
      i_pos += posErr * dt;
      float v_base = constrain(Kp_pos * posErr + Ki_pos * i_pos, -MAX_V, MAX_V);

      // Tier 2: Heading Control -> Differential Correction
      float yawErr = 0 - filteredYaw; // Setpoint is always 0
      i_yaw = constrain(i_yaw + yawErr * dt, -1.0, 1.0);
      float yawDeriv = (yawErr - lastYawErr) / dt;
      
      float v_corr = constrain((Kp_yaw * yawErr) + (Ki_yaw * i_yaw) + (Kd_yaw * yawDeriv), -MAX_CORR, MAX_CORR);
      lastYawErr = yawErr;

      // Tier 1: Velocity Control Allocation
      executeSpeedPID(v_base - v_corr, v_base + v_corr, vL_act, vR_act, dt);
    }
  }

  // Telemetry (10Hz)
  static int sc = 0;
  if (++sc >= 2) {
    sc = 0;
    Serial.print("{T:"); Serial.print(posX, 3); Serial.print(",");
    Serial.print(filteredYaw, 3); Serial.print(",");
    Serial.print(vL_act, 2); Serial.print(","); Serial.print(vR_act, 2); Serial.print(",");
    Serial.print(goalX, 2); Serial.println("}");
  }
}

// ============================================================
// 7. INTERRUPT SERVICE ROUTINES
// ============================================================
ISR(PCINT1_vect) {
  uint8_t c = PINC, d = c ^ last_PINC; last_PINC = c;
  if (d & 0x01) pulseL++; if (d & 0x02) pulseL++; if (d & 0x04) pulseR++; 
}
ISR(PCINT2_vect) {
  uint8_t c = PIND, d = c ^ last_PIND; last_PIND = c;
  if (d & 0x10) pulseR++; 
}