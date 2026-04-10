"""
MADS (Modified Assistive Driving Safety) - Decouples lateral control from longitudinal control.

Ported from sunnypilot (Copyright (c) 2021-, Haibin Wen, sunnypilot contributors, MIT License).
Simplified for stock openpilot with Hyundai focus.
"""

from cereal import log, car, custom
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.selfdrived.events import Events, ET
from openpilot.selfdrive.selfdrived.state import SOFT_DISABLE_TIME

MadsStateEnum = custom.MadsState.State
ButtonType = car.CarState.ButtonEvent.Type
EventName = log.OnroadEvent.EventName
GearShifter = car.CarState.GearShifter
SafetyModel = car.CarParams.SafetyModel


class MadsBrakeMode:
  REMAIN_ACTIVE = 0
  PAUSE = 1
  DISENGAGE = 2


MADS_ACTIVE_STATES = (MadsStateEnum.enabled, MadsStateEnum.softDisabling, MadsStateEnum.overriding)
MADS_ENABLED_STATES = (MadsStateEnum.paused, *MADS_ACTIVE_STATES)

# Events that allow transitioning to paused state instead of disabled
PAUSE_EVENTS = [EventName.wrongGear, EventName.reverseGear, EventName.brakeHold,
                EventName.doorOpen, EventName.seatbeltNotLatched, EventName.parkBrake]

# Events that only affect longitudinal - should be removed when MADS is active
LONGITUDINAL_ONLY_EVENTS = [EventName.pcmDisable, EventName.buttonCancel, EventName.wrongCruiseMode]


class MadsStateMachine:
  def __init__(self):
    self.state = MadsStateEnum.disabled
    self.soft_disable_timer = 0

  def update(self, events: Events, should_pause: bool):
    self.soft_disable_timer = max(0, self.soft_disable_timer - 1)

    # ENABLED, SOFT DISABLING, PAUSED, OVERRIDING
    if self.state != MadsStateEnum.disabled:
      if events.contains(ET.USER_DISABLE):
        if should_pause:
          self.state = MadsStateEnum.paused
        else:
          self.state = MadsStateEnum.disabled

      elif events.contains(ET.IMMEDIATE_DISABLE):
        self.state = MadsStateEnum.disabled

      else:
        # ENABLED
        if self.state == MadsStateEnum.enabled:
          if events.contains(ET.SOFT_DISABLE):
            self.state = MadsStateEnum.softDisabling
            self.soft_disable_timer = int(SOFT_DISABLE_TIME / DT_CTRL)

          elif events.contains(ET.OVERRIDE_LATERAL):
            self.state = MadsStateEnum.overriding

        # SOFT DISABLING
        elif self.state == MadsStateEnum.softDisabling:
          if not events.contains(ET.SOFT_DISABLE):
            self.state = MadsStateEnum.enabled
          elif self.soft_disable_timer <= 0:
            self.state = MadsStateEnum.disabled

        # PAUSED
        elif self.state == MadsStateEnum.paused:
          if events.contains(ET.ENABLE):
            if events.contains(ET.NO_ENTRY):
              pass  # stay paused
            else:
              if events.contains(ET.OVERRIDE_LATERAL):
                self.state = MadsStateEnum.overriding
              else:
                self.state = MadsStateEnum.enabled

        # OVERRIDING
        elif self.state == MadsStateEnum.overriding:
          if events.contains(ET.SOFT_DISABLE):
            self.state = MadsStateEnum.softDisabling
            self.soft_disable_timer = int(SOFT_DISABLE_TIME / DT_CTRL)
          elif not events.contains(ET.OVERRIDE_LATERAL):
            self.state = MadsStateEnum.enabled

    # DISABLED
    elif self.state == MadsStateEnum.disabled:
      if events.contains(ET.ENABLE):
        if events.contains(ET.NO_ENTRY):
          # Allow transitioning to paused if it's a pause-able condition
          if any(events.has(e) for e in PAUSE_EVENTS):
            self.state = MadsStateEnum.paused
        else:
          if events.contains(ET.OVERRIDE_LATERAL):
            self.state = MadsStateEnum.overriding
          else:
            self.state = MadsStateEnum.enabled

    enabled = self.state in MADS_ENABLED_STATES
    active = self.state in MADS_ACTIVE_STATES
    return enabled, active


class Mads:
  def __init__(self, CP):
    self.CP = CP
    self.params = Params()

    self.enabled = False
    self.active = False
    self.available = False
    self.state_machine = MadsStateMachine()

    # Hyundai with LDA button or CANFD can always engage MADS
    self.allow_always = False
    if self.CP.brand == "hyundai":
      from opendbc.car.hyundai.values import HyundaiFlags
      if self.CP.flags & (HyundaiFlags.HAS_LDA_BUTTON | HyundaiFlags.CANFD):
        self.allow_always = True

    # Read params on init
    self.enabled_toggle = self.params.get_bool("MadsEnabled")
    self.brake_mode = self.params.get("MadsBrakeMode", return_default=True)
    self.disengage_on_accelerator = self.params.get_bool("DisengageOnAccelerator")

    # Internal state
    self._should_pause = False
    self._lkas_enable = False
    self._lkas_disable = False
    self._enabled_prev = False
    self._stock_enabled_prev = False

  def read_params(self):
    self.brake_mode = self.params.get("MadsBrakeMode", return_default=True)

  def _pedal_pressed_non_gas(self, events: Events, CS, CS_prev) -> bool:
    """Check if pedalPressed event is from brake (not gas)."""
    if events.has(EventName.pedalPressed):
      if not (CS.gasPressed and not CS_prev.gasPressed and self.disengage_on_accelerator):
        return True
    return False

  def update_events(self, events: Events, CS, CS_prev, stock_enabled: bool):
    """Modify events for MADS behavior. Called after stock event generation."""
    if not self.enabled_toggle:
      return

    self._should_pause = False
    self._lkas_enable = False
    self._lkas_disable = False

    # When MADS is enabled but stock openpilot (cruise) is not:
    # Replace disable events with pause transitions
    if not stock_enabled and self.enabled:
      if CS.standstill:
        if events.has(EventName.doorOpen):
          events.remove(EventName.doorOpen)
          self._should_pause = True
        if events.has(EventName.seatbeltNotLatched):
          events.remove(EventName.seatbeltNotLatched)
          self._should_pause = True

      if events.has(EventName.wrongGear) and (CS.vEgo < 2.5 or CS.gearShifter == GearShifter.reverse):
        events.remove(EventName.wrongGear)
        self._should_pause = True
      if events.has(EventName.reverseGear):
        events.remove(EventName.reverseGear)
        self._should_pause = True
      if events.has(EventName.brakeHold):
        events.remove(EventName.brakeHold)
        self._should_pause = True
      if events.has(EventName.parkBrake):
        events.remove(EventName.parkBrake)
        self._should_pause = True

      # Brake mode: pause
      if self.brake_mode == MadsBrakeMode.PAUSE:
        if self._pedal_pressed_non_gas(events, CS, CS_prev):
          self._should_pause = True

      # Remove events that only affect longitudinal
      events.remove(EventName.preEnableStandstill)
      events.remove(EventName.belowEngageSpeed)
      events.remove(EventName.speedTooLow)
      events.remove(EventName.cruiseDisabled)
      events.remove(EventName.manualRestart)

    # Handle LKAS button presses (toggle MADS)
    for be in CS.buttonEvents:
      if be.type == ButtonType.lkas and be.pressed and (CS.cruiseState.available or self.allow_always):
        if self.enabled:
          if stock_enabled:
            # Both MADS and cruise are on - LKAS button disengages only MADS lateral
            # This maps to sunnypilot's manualSteeringRequired behavior
            self._lkas_disable = True
          else:
            self._lkas_disable = True
        else:
          self._lkas_enable = True

    # ACC main rising edge -> enable MADS
    if CS.cruiseState.available and not CS_prev.cruiseState.available:
      self._lkas_enable = True

    # ACC main turning off -> disable MADS
    if not CS.cruiseState.available and CS_prev.cruiseState.available:
      self._lkas_disable = True

    # Unified engagement mode: engaging cruise also engages MADS
    stock_enable_events = events.has(EventName.pcmEnable) or events.has(EventName.buttonEnable)
    if stock_enable_events and not self.enabled:
      self._lkas_enable = True

    # Brake mode: disengage
    if self.brake_mode == MadsBrakeMode.DISENGAGE:
      if self._pedal_pressed_non_gas(events, CS, CS_prev):
        if self.enabled:
          self._lkas_disable = True
        # Block enable if pedal is pressed
        if self._lkas_enable:
          self._lkas_enable = False

    # Should resume from pause?
    if self.state_machine.state == MadsStateEnum.paused:
      can_resume = True
      if self.brake_mode == MadsBrakeMode.PAUSE and self._pedal_pressed_non_gas(events, CS, CS_prev):
        can_resume = False
      if self._should_pause:
        can_resume = False
      if can_resume:
        self._lkas_enable = True

    # Add enable/disable events for the MADS state machine
    if self._lkas_enable and not self._lkas_disable:
      # Inject a synthetic enable for MADS state machine processing
      events.add(EventName.buttonEnable)
    if self._lkas_disable:
      events.add(EventName.buttonCancel)

    # Remove longitudinal-only events so they don't affect stock state machine
    # when MADS is managing lateral independently
    for evt in LONGITUDINAL_ONLY_EVENTS:
      events.remove(evt)
    events.remove(EventName.pedalPressed)

    self._stock_enabled_prev = stock_enabled

  def update(self, events: Events, CS, CS_prev, stock_enabled: bool, initialized: bool):
    """Main MADS update. Called each control cycle."""
    if not self.enabled_toggle:
      self.available = False
      self.enabled = False
      self.active = False
      return

    self.available = True

    self.update_events(events, CS, CS_prev, stock_enabled)

    if not self.CP.passive and initialized:
      self.enabled, self.active = self.state_machine.update(events, self._should_pause)

    self._enabled_prev = self.enabled
