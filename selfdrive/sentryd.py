#!/usr/bin/env python3
import numpy as np
from cereal import messaging

THRESHOLD = 0.03  # Adjust as necessary based on sensitivity requirements


class SentryMode:
  def __init__(self):
    self.sm = messaging.SubMaster(['accelerometer'], poll=['accelerometer'])
    self.prev_accel = np.zeros(3)
    self.initialized = False

  def get_movement_type(self, current, previous):
    diff = np.abs(current - previous)
    ax_mapping = {0: "X-axis", 1: "Y-axis", 2: "Z-axis"}
    dominant_axis = np.argmax(diff)
    return ax_mapping[dominant_axis]

  def update(self):
    sensor = self.sm['accelerometer']
    
    # Try accessing fields with dot notation
    accel_data = sensor.acceleration.v
    curr_accel = np.array(accel_data)

    if not self.initialized:
      self.prev_accel = curr_accel
      self.initialized = True
      return

    magnitude_prev = np.linalg.norm(self.prev_accel)
    magnitude_curr = np.linalg.norm(curr_accel)

    delta = abs(magnitude_curr - magnitude_prev)

    if delta > THRESHOLD:
      movement_type = self.get_movement_type(curr_accel, self.prev_accel)
      print("Movement: {}, Value: {}".format(movement_type, delta))

    self.prev_accel = curr_accel

  def start(self):
    while True:
      self.sm.update()
      self.update()


def main():
  sentry_mode = SentryMode()
  sentry_mode.start()


if __name__ == "__main__":
  main()
