import os
import pyray as rl
from cereal import log

from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigMultiParamToggle
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.ui_state import ui_state

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants
LAYOUTS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "layouts"))
HOTZSLIP_FRAME_PATHS = [
  os.path.join(LAYOUTS_DIR, f"frame_{idx}_delay-0.15s.gif") for idx in range(9)
]
HOTZSLIP_FRAME_DURATION = 0.12
HOTZSLIP_SPEED_X = 110.0
HOTZSLIP_SPEED_Y = 78.0


class HotzModeControl(BigParamControl):
  def __init__(self):
    super().__init__("hotz mode", "HotzMode")
    self._hotzslip_textures = [rl.load_texture(path) for path in HOTZSLIP_FRAME_PATHS if os.path.exists(path)]

  def _frame_index(self) -> int:
    if len(self._hotzslip_textures) <= 1:
      return 0
    cycle_len = len(self._hotzslip_textures) * 2 - 2
    phase = int(rl.get_time() / HOTZSLIP_FRAME_DURATION) % cycle_len
    if phase < len(self._hotzslip_textures):
      return phase
    return cycle_len - phase

  def _reflect(self, value: float, limit: float) -> float:
    if limit <= 0:
      return 0.0
    span = limit * 2.0
    pos = value % span
    return pos if pos <= limit else span - pos

  def _dvd_pose(self, btn_y: float, size: float) -> tuple[rl.Vector2, float]:
    margin = 4.0
    left = self._rect.x + margin
    top = btn_y + margin
    width = max(1.0, self._rect.width - margin * 2 - size)
    height = max(1.0, self._rect.height - margin * 2 - size)
    t = rl.get_time()
    x = left + self._reflect(t * HOTZSLIP_SPEED_X, width)
    y = top + self._reflect(t * HOTZSLIP_SPEED_Y, height)
    return rl.Vector2(x + size / 2, y + size / 2), 0.0

  def _render(self, _):
    txt_bg, btn_x, btn_y, scale = self._handle_background()
    rl.draw_texture_ex(txt_bg, (btn_x, btn_y), 0, scale, rl.WHITE)

    if len(self._hotzslip_textures) > 0:
      frame_idx = 0 if not self._checked else self._frame_index()
      texture = self._hotzslip_textures[frame_idx]
      if texture.width > 0 and texture.height > 0:
        src = rl.Rectangle(0, 0, texture.width, texture.height)
        size = 58.0
        center, angle = self._dvd_pose(btn_y, size)
        dest = rl.Rectangle(center.x, center.y, size, size)
        rl.draw_texture_pro(texture, src, dest, rl.Vector2(size / 2, size / 2), angle, rl.Color(255, 255, 255, 235))

    self._draw_content(btn_y)


class TogglesLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    hotz_mode_toggle = HotzModeControl()
    self._personality_toggle = BigMultiParamToggle("driving personality", "LongitudinalPersonality", ["aggressive", "standard", "relaxed"])
    self._experimental_btn = BigParamControl("experimental mode", "ExperimentalMode")
    is_metric_toggle = BigParamControl("use metric units", "IsMetric")
    ldw_toggle = BigParamControl("lane departure warnings", "IsLdwEnabled")
    always_on_dm_toggle = BigParamControl("always-on driver monitor", "AlwaysOnDM")
    record_front = BigParamControl("record & upload driver camera", "RecordFront", toggle_callback=restart_needed_callback)
    record_mic = BigParamControl("record & upload mic audio", "RecordAudio", toggle_callback=restart_needed_callback)
    enable_openpilot = BigParamControl("enable openpilot", "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback)

    self._scroller.add_widgets([
      hotz_mode_toggle,
      self._personality_toggle,
      self._experimental_btn,
      is_metric_toggle,
      ldw_toggle,
      always_on_dm_toggle,
      record_front,
      record_mic,
      enable_openpilot,
    ])

    # Toggle lists
    self._refresh_toggles = (
      ("HotzMode", hotz_mode_toggle),
      ("ExperimentalMode", self._experimental_btn),
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("RecordFront", record_front),
      ("RecordAudio", record_mic),
      ("OpenpilotEnabledToggle", enable_openpilot),
    )

    enable_openpilot.set_enabled(lambda: not ui_state.engaged)
    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))
    record_mic.set_enabled(lambda: not ui_state.engaged)

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()

    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._personality_toggle.set_value(self._personality_toggle._options[personality])
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # CP gating for experimental mode
    if ui_state.CP is not None:
      if ui_state.has_longitudinal_control:
        self._experimental_btn.set_visible(True)
        self._personality_toggle.set_visible(True)
      else:
        # no long for now
        self._experimental_btn.set_visible(False)
        self._experimental_btn.set_checked(False)
        self._personality_toggle.set_visible(False)
        ui_state.params.remove("ExperimentalMode")

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))
