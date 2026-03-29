import math
import threading
import time

try:
  from inputs import UnpluggedError, get_gamepad
except ImportError:
  UnpluggedError = OSError
  get_gamepad = None


class UIJoystickManager:
  def __init__(self):
    self.enabled = get_gamepad is not None
    self.connected = False
    self._lock = threading.Lock()
    self._running = False
    self._thread = None

    self._move_axis = "ABS_Y"
    self._turn_axis = "ABS_Z"
    self._menu_x_axis = "ABS_X"
    self._menu_y_axis = "ABS_Y"
    self._flip_map = {"ABS_RY": self._move_axis}
    self._axes_values = {
      self._move_axis: 0.0,
      self._turn_axis: 0.0,
      self._menu_x_axis: 0.0,
      self._menu_y_axis: 0.0,
    }
    self._min_axis_value = {name: 0.0 for name in self._axes_values}
    self._max_axis_value = {name: 255.0 for name in self._axes_values}
    self._hat_x = 0.0
    self._hat_y = 0.0
    self._button_edges: dict[str, bool] = {}
    self._button_states: dict[str, int] = {}
    self._debug_order: list[str] = []
    self._last_debug_line = ""

    self.move = 0.0
    self.turn = 0.0
    self.menu_x = 0.0
    self.menu_y = 0.0

  def start(self):
    if not self.enabled or self._running:
      return
    self._running = True
    self._thread = threading.Thread(target=self._poll_loop, daemon=True)
    self._thread.start()

  def stop(self):
    self._running = False

  def get_game_axes(self) -> tuple[float, float]:
    with self._lock:
      return self.move, self.turn

  def get_menu_axes(self) -> tuple[float, float]:
    with self._lock:
      return self.menu_x, self.menu_y

  def consume_primary(self) -> bool:
    return self._consume_any(("BTN_SOUTH", "BTN_Z"))

  def consume_secondary(self) -> bool:
    return self._consume_any(("BTN_EAST", "BTN_B", "BTN_SELECT"))

  def consume_alt_fire(self) -> bool:
    return self._consume_any(("BTN_WEST",))

  def consume_restart(self) -> bool:
    return self._consume_any(("BTN_TL2", "BTN_TR2"))

  def _consume_any(self, names: tuple[str, ...]) -> bool:
    with self._lock:
      hit = any(self._button_edges.get(name, False) for name in names)
      if hit:
        for name in names:
          self._button_edges[name] = False
      return hit

  def _poll_loop(self):
    while self._running:
      try:
        events = get_gamepad()
      except (OSError, UnpluggedError):
        with self._lock:
          self.connected = False
          self.move = 0.0
          self.turn = 0.0
          self.menu_x = 0.0
          self.menu_y = 0.0
          self._emit_debug_locked(reason="disconnected")
        time.sleep(0.1)
        continue

      with self._lock:
        self.connected = True
      for joystick_event in events:
        self._handle_event(joystick_event.code, joystick_event.state)

  def _handle_event(self, code: str, state: int):
    if code in self._flip_map:
      code = self._flip_map[code]
      state = -state

    with self._lock:
      if code in ("ABS_HAT0X", "ABS_HAT0Y"):
        self._remember_debug(code)
        if code == "ABS_HAT0X":
          self._hat_x = float(state)
        else:
          self._hat_y = float(state)
        self._button_states[code] = state
        self._update_menu_axes()
        self._emit_debug_locked(reason=code)
        return

      if code.startswith("BTN_"):
        self._remember_debug(code)
        if state == 1:
          self._button_edges[code] = True
        self._button_states[code] = state
        self._emit_debug_locked(reason=code)
        return

      if code in self._axes_values:
        self._remember_debug(code)
        self._max_axis_value[code] = max(state, self._max_axis_value[code])
        self._min_axis_value[code] = min(state, self._min_axis_value[code])
        low = self._min_axis_value[code]
        high = self._max_axis_value[code]
        if high == low:
          norm = 0.0
        else:
          norm = -float((2.0 * (state - low) / (high - low)) - 1.0)
        norm = norm if abs(norm) > 0.05 else 0.0
        expo = 0.4
        self._axes_values[code] = expo * norm ** 3 + (1 - expo) * norm
        self._button_states[code] = state
        self.move = self._axes_values[self._move_axis]
        self.turn = -self._axes_values[self._turn_axis]
        self._update_menu_axes()
        self._emit_debug_locked(reason=code)

  def _update_menu_axes(self):
    analog_x = self._axes_values[self._menu_x_axis]
    analog_y = self._axes_values[self._menu_y_axis]
    self.menu_x = self._hat_x if abs(self._hat_x) >= abs(analog_x) else analog_x
    self.menu_y = self._hat_y if abs(self._hat_y) >= abs(analog_y) else analog_y

  def _remember_debug(self, code: str):
    if code not in self._debug_order:
      self._debug_order.append(code)

  def _emit_debug_locked(self, reason: str):
    parts = [
      f"connected={int(self.connected)}",
      f"move={self.move:+.2f}",
      f"turn={self.turn:+.2f}",
      f"menu_x={self.menu_x:+.2f}",
      f"menu_y={self.menu_y:+.2f}",
      f"hat_x={self._hat_x:+.0f}",
      f"hat_y={self._hat_y:+.0f}",
      f"reason={reason}",
    ]
    for name in self._debug_order:
      value = self._button_states.get(name)
      if value is None:
        continue
      if isinstance(value, float):
        if math.isfinite(value):
          parts.append(f"{name}={value:+.2f}")
      else:
        parts.append(f"{name}={value}")
    line = "[ui joystick] " + " ".join(parts)
    if line != self._last_debug_line:
      self._last_debug_line = line
      print(line, flush=True)


ui_joystick = UIJoystickManager()
