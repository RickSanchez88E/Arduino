/**
 * Elegoo Smart Robot Car V4.0 - Vision-Guided Navigation Firmware
 * 
 * Architecture: 
 *   Mac (navigator.py) sends velocity commands via WiFi at ~10Hz
 *   Arduino executes velocity control via dual independent wheel PID
 *
 * Commands (from Mac via WiFi/Serial):
 *   {MOVE:v,w}     - Set linear velocity (m/s) and angular velocity (rad/s)
 *   {STOP}         - Emergency stop, clear all state
 *   {ZERO}         - Reset heading reference to current orientation
 *   {PING}         - Heartbeat, responds with {PONG}
 *
 * Telemetry (to Mac):
 *   {T:vL,vR,yaw}  - Actual wheel velocities (m/s) and filtered heading (rad)
 *   {INFO:msg}     - Status messages
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_ADXL345_U.h>
#include <Adafruit_HMC5883_U.h>

// ============================================================
// 1. PHYSICAL CONSTANTS & TUNING
// ============================================================

// -- Robot dimensions --
const float WHEEL_BASE   = 0.18f;     // Distance between wheels (m)
const float WHEEL_DIAM   = 0.066f;    // Wheel diameter (m)
const float DIST_PER_PULSE = (3.14159f * WHEEL_DIAM) / 1920.0f;

// -- Velocity PID (inner loop) --
float Kp_vel = 100.0f;
float Ki_vel = 0.0f;

// -- Constraints --
const float MAX_V      = 0.20f;    // Max linear velocity (m/s)
const float MAX_W      = 2.0f;     // Max angular velocity (rad/s)
const float FF_GAIN    = 2200.0f;  // Feed-forward: velocity -> PWM
const float MIN_PWM    = 45;       // Minimum PWM to overcome static friction
const float MAG_ALPHA  = 0.5f;     // Magnetometer EMA filter

// -- Safety --
const unsigned long CMD_TIMEOUT_MS = 500;  // Stop if no command for 500ms

// ============================================================
// 2. HARDWARE & STATE
// ============================================================
Adafruit_ADXL345_Unified accel = Adafruit_ADXL345_Unified(12345);
Adafruit_HMC5883_Unified mag   = Adafruit_HMC5883_Unified(12346);

// Target velocities (set by Mac)
float target_v = 0;     // Linear velocity (m/s), positive = forward
float target_w = 0;     // Angular velocity (rad/s), positive = CCW

// Heading
float yawOffset   = 0;
float filteredYaw = 0;

// PID accumulators
float i_velL = 0, i_velR = 0;

// Motor state
bool dirL_fwd = true, dirR_fwd = true;
volatile long pulseL = 0, pulseR = 0;
uint8_t last_PINC, last_PIND;

// Command timeout
unsigned long lastCmdTime = 0;

// ============================================================
// 3. SENSOR: TILT-COMPENSATED MAGNETOMETER
// ============================================================
float getRawHeading() {
    sensors_event_t a, m;
    accel.getEvent(&a); mag.getEvent(&m);

    float roll  = atan2(a.acceleration.y, a.acceleration.z);
    float pitch = atan2(-a.acceleration.x,
                        sqrt(a.acceleration.y * a.acceleration.y +
                             a.acceleration.z * a.acceleration.z));

    float Xh = m.magnetic.x * cos(pitch) + m.magnetic.z * sin(pitch);
    float Yh = m.magnetic.x * sin(roll) * sin(pitch)
             + m.magnetic.y * cos(roll)
             - m.magnetic.z * sin(roll) * cos(pitch);

    return atan2(Yh, Xh);
}

// ============================================================
// 4. VELOCITY PID (ACTUATOR LAYER)
// ============================================================
void executeSpeedPID(float vL_target, float vR_target,
                     float vL_actual, float vR_actual, float dt) {
    float errL = vL_target - vL_actual;
    float errR = vR_target - vR_actual;

    // Integration with anti-windup
    i_velL = constrain(i_velL + errL * dt, -60, 60);
    i_velR = constrain(i_velR + errR * dt, -60, 60);

    // Feed-forward + PID
    float pwmL = (vL_target * FF_GAIN) + (errL * Kp_vel) + (i_velL * Ki_vel);
    float pwmR = (vR_target * FF_GAIN) + (errR * Kp_vel) + (i_velR * Ki_vel);

    // Full stop
    if (abs(vL_target) < 0.005 && abs(vR_target) < 0.005) {
        pwmL = 0; pwmR = 0; i_velL = 0; i_velR = 0;
    } else {
        // Static friction compensation
        if (abs(pwmL) < MIN_PWM) pwmL = (pwmL > 0) ? MIN_PWM : -MIN_PWM;
        if (abs(pwmR) < MIN_PWM) pwmR = (pwmR > 0) ? MIN_PWM : -MIN_PWM;
    }

    // Write to hardware
    dirL_fwd = (pwmL >= 0); dirR_fwd = (pwmR >= 0);
    digitalWrite(8, dirL_fwd ? LOW : HIGH);
    digitalWrite(7, dirR_fwd ? LOW : HIGH);
    analogWrite(6, (uint8_t)constrain(abs(pwmL), 0, 255));
    analogWrite(5, (uint8_t)constrain(abs(pwmR), 0, 255));
}

// ============================================================
// 5. COMMAND PARSER
// ============================================================
void parseCommand(String &cmd) {
    cmd.trim();
    lastCmdTime = millis();

    if (cmd.startsWith("{MOVE:")) {
        // {MOVE:v,w} - set target velocities
        int ci = cmd.indexOf(':');
        int mi = cmd.indexOf(',', ci);
        int ei = cmd.indexOf('}');
        if (ci > 0 && mi > ci && ei > mi) {
            target_v = constrain(cmd.substring(ci + 1, mi).toFloat(), -MAX_V, MAX_V);
            target_w = constrain(cmd.substring(mi + 1, ei).toFloat(), -MAX_W, MAX_W);
        }
    }
    else if (cmd.indexOf("STOP") >= 0) {
        target_v = 0; target_w = 0;
        i_velL = 0; i_velR = 0;
        executeSpeedPID(0, 0, 0, 0, 0.05);
        Serial.println("{INFO:stopped}");
    }
    else if (cmd.indexOf("ZERO") >= 0) {
        yawOffset = getRawHeading();
        filteredYaw = 0;
        Serial.println("{INFO:zeroed}");
    }
    else if (cmd.indexOf("PING") >= 0) {
        Serial.println("{PONG}");
    }
}

// ============================================================
// 6. SETUP
// ============================================================
void setup() {
    Serial.begin(9600);
    Wire.begin();
    accel.begin();
    mag.begin();

    pinMode(3, OUTPUT); digitalWrite(3, HIGH);  // Standby
    pinMode(8, OUTPUT); pinMode(6, OUTPUT);     // Left motor
    pinMode(7, OUTPUT); pinMode(5, OUTPUT);     // Right motor

    // Sensor warm-up
    Serial.println("{INFO:calibrating}");
    delay(500);

    float sumYaw = 0;
    for (int i = 0; i < 20; i++) {
        sumYaw += getRawHeading();
        delay(10);
    }
    yawOffset = sumYaw / 20.0f;
    filteredYaw = 0;

    // Encoder interrupts
    cli();
    PCICR  |= (1 << PCIE1) | (1 << PCIE2);
    PCMSK1 |= (1 << PCINT8) | (1 << PCINT9) | (1 << PCINT10);
    PCMSK2 |= (1 << PCINT20);
    sei();

    lastCmdTime = millis();
    Serial.println("{INFO:ready}");
}

// ============================================================
// 7. MAIN LOOP (20Hz / 50ms)
// ============================================================
void loop() {
    // -- Command parsing --
    static String buf = "";
    while (Serial.available()) {
        char ch = Serial.read();
        buf += ch;
        if (ch == '}') {
            parseCommand(buf);
            buf = "";
        }
    }

    // -- Periodic execution (50ms) --
    static unsigned long lastMs = 0;
    if (millis() - lastMs < 50) return;
    float dt = (millis() - lastMs) / 1000.0f;
    lastMs = millis();

    // A. Odometry
    cli();
    long cL = pulseL; pulseL = 0;
    long cR = pulseR; pulseR = 0;
    sei();

    float dL = cL * DIST_PER_PULSE * (dirL_fwd ? 1 : -1);
    float dR = cR * DIST_PER_PULSE * (dirR_fwd ? 1 : -1);
    float vL_act = dL / dt;
    float vR_act = dR / dt;

    // B. Heading update
    float raw = getRawHeading() - yawOffset;
    float angleDiff = raw - filteredYaw;
    if (angleDiff >  PI) angleDiff -= 2.0f * PI;
    if (angleDiff < -PI) angleDiff += 2.0f * PI;
    filteredYaw += MAG_ALPHA * angleDiff;

    // C. Safety: stop if no commands for too long
    if (millis() - lastCmdTime > CMD_TIMEOUT_MS) {
        target_v = 0;
        target_w = 0;
    }

    // D. Convert (v, w) to wheel velocities
    //    v = (vL + vR) / 2
    //    w = (vR - vL) / WHEEL_BASE
    //    => vL = v - w * WHEEL_BASE / 2
    //    => vR = v + w * WHEEL_BASE / 2
    float vL_target = target_v - target_w * WHEEL_BASE / 2.0f;
    float vR_target = target_v + target_w * WHEEL_BASE / 2.0f;

    executeSpeedPID(vL_target, vR_target, vL_act, vR_act, dt);

    // E. Telemetry at 10Hz (every other cycle)
    static int sc = 0;
    if (++sc >= 2) {
        sc = 0;
        Serial.print("{T:");
        Serial.print(vL_act, 3); Serial.print(",");
        Serial.print(vR_act, 3); Serial.print(",");
        Serial.print(filteredYaw, 3);
        Serial.println("}");
    }
}

// ============================================================
// 8. INTERRUPT SERVICE ROUTINES
// ============================================================
ISR(PCINT1_vect) {
    uint8_t c = PINC, d = c ^ last_PINC; last_PINC = c;
    if (d & 0x01) pulseL++;
    if (d & 0x02) pulseL++;
    if (d & 0x04) pulseR++;
}
ISR(PCINT2_vect) {
    uint8_t c = PIND, d = c ^ last_PIND; last_PIND = c;
    if (d & 0x10) pulseR++;
}