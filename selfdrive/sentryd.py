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

    self.prev_accel = None
    self.sentry_status = False


  def get_movement_type(self, current, previous):
    ax_mapping = {0: "X", 1: "Y", 2: "Z"}
    dominant_axis = np.argmax(np.abs(current - previous))
    return ax_mapping[dominant_axis]


  def update(self):    
    # Extract acceleration data
    curr_accel = np.array(self.sm['accelerometer'].acceleration.v)

    print("self.prev_accel {}".format(self.prev_accel))
    print("curr_accel {}".format(curr_accel))

    # Initialize
    if self.prev_accel is None:
      print("YESSSSSSSSS")
      self.prev_accel = curr_accel
      print("self.prev_accel {}".format(self.prev_accel))
      print("curr_accel {}".format(curr_accel))

    print("self.prev_accel {}".format(self.prev_accel))
    print("curr_accel {}".format(curr_accel))

    # Calculate magnitude change
    delta = abs(np.linalg.norm(curr_accel) - np.linalg.norm(self.prev_accel))

    # Trigger Check
    if delta > SENSITIVITY_THRESHOLD:
      movement_type = self.get_movement_type(curr_accel, self.prev_accel)
      print("Movement {} - {}".format(movement_type, delta))
      self.last_timestamp = time.monotonic()
      self.sentry_status = True

    # Trigger Reset
    elif self.sentry_status and time.monotonic() - self.last_timestamp > TRIGGERED_TIME:
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
