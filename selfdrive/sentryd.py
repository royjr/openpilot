#!/usr/bin/env python3
import numpy as np

from cereal import messaging


class SentryMode:
  def __init__(self):
    self.sm = messaging.SubMaster(['accelerometer'], poll=['accelerometer'])

    self.prev_accel = np.zeros(3)
    self.initialized = False


  def update(self):
    for sensor in self.sm['accelerometer']:
      # do stuff here


  def start(self):
    while 1:
      self.sm.update()
      self.update()


def main():
  sentry_mode = SentryMode()
  sentry_mode.start()


if __name__ == "__main__":
  main()
