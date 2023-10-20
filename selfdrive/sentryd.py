#!/usr/bin/env python3
import numpy as np
from cereal import messaging
import time

SENSITIVITY_THRESHOLD = 0.03
TRIGGERED_TIME = 2


class SentryMode:

  def __init__(self):
    self.sm = messaging.SubMaster(['accelerometer'], poll=['accelerometer'])
    # self.pm = messaging.PubMaster(['sentryState'])

    self.prev_accel = np.zeros(3)
    self.initialized = False
    self.sentry_status = False
    self.last_timestamp = 0


  def get_movement_type(self, current, previous):
    diff = np.abs(current - previous)
    ax_mapping = {0: "X-axis", 1: "Y-axis", 2: "Z-axis"}
    dominant_axis = np.argmax(diff)
    return ax_mapping[dominant_axis]


  def update(self):
    sensor = self.sm['accelerometer']
    
    # Extract acceleration data
    accel_data = sensor.acceleration.v
    curr_accel = np.array(accel_data)

    if not self.initialized:
      self.prev_accel = curr_accel
      self.initialized = True
      return

    # Calculate magnitude change
    magnitude_prev = np.linalg.norm(self.prev_accel)
    magnitude_curr = np.linalg.norm(curr_accel)

    delta = abs(magnitude_curr - magnitude_prev)

    # Triggered
    if delta > SENSITIVITY_THRESHOLD:
      movement_type = self.get_movement_type(curr_accel, self.prev_accel)
      print("Movement: {}, Value: {}".format(movement_type, delta))
      self.last_timestamp = time.monotonic()
      self.sentry_status = True

    # Trigger Reset
    now_timestamp = time.monotonic()
    if now_timestamp - self.last_timestamp > TRIGGERED_TIME and self.sentry_status:
      self.sentry_status = False
      print("Movement Ended")

    self.prev_accel = curr_accel


  # def publish(self):
  #   sentry_state = messaging.new_message('sentryState')
  #   sentry_state.sentryState.status = bool(self.sentry_status)

  #   self.pm.send('sentryState', sentry_state)


  def start(self):
    while True:
      self.sm.update()
      self.update()
      # self.publish()


def main():
  sentry_mode = SentryMode()
  sentry_mode.start()


if __name__ == "__main__":
  main()
