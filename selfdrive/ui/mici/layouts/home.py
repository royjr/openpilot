import datetime
import math
import time

from cereal import log
import pyray as rl
from collections.abc import Callable
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.layouts import HBoxLayout
from openpilot.system.ui.widgets.icon_widget import IconWidget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.version import RELEASE_BRANCHES

HEAD_BUTTON_FONT_SIZE = 40
HOME_PADDING = 8

NetworkType = log.DeviceState.NetworkType

NETWORK_TYPES = {
  NetworkType.none: "Offline",
  NetworkType.wifi: "WiFi",
  NetworkType.cell2G: "2G",
  NetworkType.cell3G: "3G",
  NetworkType.cell4G: "LTE",
  NetworkType.cell5G: "5G",
  NetworkType.ethernet: "Ethernet",
}


class NetworkIcon(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 54, 44))  # max size of all icons
    self._net_type = NetworkType.none
    self._net_strength = 0

    self._wifi_slash_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_slash.png", 50, 44)
    self._wifi_none_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_none.png", 50, 37)
    self._wifi_low_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_low.png", 50, 37)
    self._wifi_medium_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_medium.png", 50, 37)
    self._wifi_full_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_full.png", 50, 37)

    self._cell_none_txt = gui_app.texture("icons_mici/settings/network/cell_strength_none.png", 54, 36)
    self._cell_low_txt = gui_app.texture("icons_mici/settings/network/cell_strength_low.png", 54, 36)
    self._cell_medium_txt = gui_app.texture("icons_mici/settings/network/cell_strength_medium.png", 54, 36)
    self._cell_high_txt = gui_app.texture("icons_mici/settings/network/cell_strength_high.png", 54, 36)
    self._cell_full_txt = gui_app.texture("icons_mici/settings/network/cell_strength_full.png", 54, 36)

  def _update_state(self):
    device_state = ui_state.sm['deviceState']
    self._net_type = device_state.networkType
    strength = device_state.networkStrength
    self._net_strength = max(0, min(5, strength.raw + 1)) if strength.raw > 0 else 0

  def _render(self, _):
    if self._net_type == NetworkType.wifi:
      # There is no 1
      draw_net_txt = {0: self._wifi_none_txt,
                      2: self._wifi_low_txt,
                      3: self._wifi_medium_txt,
                      4: self._wifi_full_txt,
                      5: self._wifi_full_txt}.get(self._net_strength, self._wifi_low_txt)
    elif self._net_type in (NetworkType.cell2G, NetworkType.cell3G, NetworkType.cell4G, NetworkType.cell5G):
      draw_net_txt = {0: self._cell_none_txt,
                      2: self._cell_low_txt,
                      3: self._cell_medium_txt,
                      4: self._cell_high_txt,
                      5: self._cell_full_txt}.get(self._net_strength, self._cell_none_txt)
    else:
      draw_net_txt = self._wifi_slash_txt

    draw_x = self._rect.x + (self._rect.width - draw_net_txt.width) / 2
    draw_y = self._rect.y + (self._rect.height - draw_net_txt.height) / 2

    if draw_net_txt == self._wifi_slash_txt:
      # Offset by difference in height between slashless and slash icons to make center align match
      draw_y -= (self._wifi_slash_txt.height - self._wifi_none_txt.height) / 2

    rl.draw_texture_ex(draw_net_txt, rl.Vector2(draw_x, draw_y), 0.0, 1.0, rl.Color(255, 255, 255, int(255 * 0.9)))


class MiciHomeLayout(Widget):
  def __init__(self):
    super().__init__()
    self._on_settings_click: Callable | None = None
    self._game_callbacks: dict[str, Callable | None] = {}
    self._game_options: list[tuple[str, str, rl.Color]] = [
      ("openpilot", "open", rl.WHITE),
      ("doompilot", "doom", rl.Color(226, 44, 44, 255)),
      ("dinopilot", "dino", rl.Color(80, 170, 80, 255)),
      ("snakepilot", "snake", rl.Color(176, 96, 255, 255)),
    ]
    self._selected_game_idx = 0
    self._anim_from_idx = 0
    self._anim_direction = 0
    self._anim_started_at = 0.0
    self._anim_duration = 0.18

    self._last_refresh = 0
    self._mouse_down_t: None | float = None
    self._did_long_press = False
    self._is_pressed_prev = False
    self._press_pos: MousePos | None = None
    self._title_press_pos: MousePos | None = None
    self._title_touch_active = False
    self._gesture_consumed = False

    self._version_text = None
    self._experimental_mode = False

    self._experimental_icon = IconWidget("icons_mici/experimental_mode.png", (48, 48))
    self._mic_icon = IconWidget("icons_mici/microphone.png", (32, 46))

    self._status_bar_layout = HBoxLayout([
      IconWidget("icons_mici/settings.png", (48, 48), opacity=0.9),
      NetworkIcon(),
      self._experimental_icon,
      self._mic_icon,
    ], spacing=18)

    self._doom_label = UnifiedLabel("open", font_size=96, font_weight=FontWeight.DISPLAY, text_color=rl.WHITE,
                                    max_width=480, wrap_text=False)
    self._pilot_label = UnifiedLabel("pilot", font_size=96, font_weight=FontWeight.DISPLAY, text_color=rl.WHITE,
                                     max_width=480, wrap_text=False)
    self._incoming_doom_label = UnifiedLabel("open", font_size=96, font_weight=FontWeight.DISPLAY, text_color=rl.WHITE,
                                             max_width=480, wrap_text=False)
    self._incoming_pilot_label = UnifiedLabel("pilot", font_size=96, font_weight=FontWeight.DISPLAY, text_color=rl.WHITE,
                                              max_width=480, wrap_text=False)
    self._version_label = UnifiedLabel("", font_size=36, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._large_version_label = UnifiedLabel("", font_size=64, text_color=rl.GRAY, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._date_label = UnifiedLabel("", font_size=36, text_color=rl.GRAY, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._branch_label = UnifiedLabel("", font_size=36, text_color=rl.GRAY, font_weight=FontWeight.ROMAN, scroll=True)
    self._version_commit_label = UnifiedLabel("", font_size=36, text_color=rl.GRAY, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)

  def show_event(self):
    super().show_event()
    self._version_text = self._get_version_text()
    self._update_params()

  def _update_params(self):
    self._experimental_mode = ui_state.params.get_bool("ExperimentalMode")

  def _update_state(self):
    if self.is_pressed and not self._is_pressed_prev:
      self._mouse_down_t = time.monotonic()
    elif not self.is_pressed and self._is_pressed_prev:
      self._mouse_down_t = None
      self._did_long_press = False
    self._is_pressed_prev = self.is_pressed

    if self._mouse_down_t is not None:
      if time.monotonic() - self._mouse_down_t > 0.5:
        # long gating for experimental mode - only allow toggle if longitudinal control is available
        if ui_state.has_longitudinal_control:
          self._experimental_mode = not self._experimental_mode
          ui_state.params.put("ExperimentalMode", self._experimental_mode)
        self._mouse_down_t = None
        self._did_long_press = True

    if rl.get_time() - self._last_refresh > 5.0:
      # Update version text
      self._version_text = self._get_version_text()
      self._last_refresh = rl.get_time()
      self._update_params()

  def set_callbacks(self, on_settings: Callable | None = None, on_doom: Callable | None = None,
                    on_dino: Callable | None = None, on_snake: Callable | None = None):
    self._on_settings_click = on_settings
    self._game_callbacks = {
      "doompilot": on_doom,
      "dinopilot": on_dino,
      "snakepilot": on_snake,
    }

  def current_game_key(self) -> str:
    return self._game_options[self._selected_game_idx][0]

  def _set_selected_game(self, idx: int):
    idx %= len(self._game_options)
    if idx == self._selected_game_idx:
      return
    self._anim_from_idx = self._selected_game_idx
    self._selected_game_idx = idx
    self._anim_direction = 1 if idx > self._anim_from_idx else -1
    if self._anim_from_idx == len(self._game_options) - 1 and idx == 0:
      self._anim_direction = 1
    elif self._anim_from_idx == 0 and idx == len(self._game_options) - 1:
      self._anim_direction = -1
    self._anim_started_at = rl.get_time()

  def _launch_selected_game(self):
    callback = self._game_callbacks.get(self.current_game_key())
    if callback is not None:
      callback()

  def cycle_selected_game(self, delta: int):
    self._set_selected_game(self._selected_game_idx + delta)

  def launch_selected_game(self):
    self._launch_selected_game()

  def _with_alpha(self, color, alpha: int) -> rl.Color:
    if hasattr(color, "r"):
      return rl.Color(color.r, color.g, color.b, alpha)
    return rl.Color(color[0], color[1], color[2], alpha)

  def _title_rect(self) -> rl.Rectangle:
    left = min(self._doom_label.rect.x, self._pilot_label.rect.x)
    top = min(self._doom_label.rect.y, self._pilot_label.rect.y)
    right = max(self._doom_label.rect.x + self._doom_label.rect.width, self._pilot_label.rect.x + self._pilot_label.rect.width)
    bottom = max(self._doom_label.rect.y + self._doom_label.rect.height, self._pilot_label.rect.y + self._pilot_label.rect.height)
    return rl.Rectangle(left, top, right - left, bottom - top)

  def _handle_mouse_press(self, mouse_pos: MousePos):
    self._press_pos = mouse_pos
    self._title_touch_active = rl.check_collision_point_rec(mouse_pos, self._title_rect())
    self._title_press_pos = mouse_pos if self._title_touch_active else None
    self._gesture_consumed = False

  def _handle_mouse_event(self, mouse_event):
    if self._press_pos is None or not mouse_event.left_down:
      return

    dx = mouse_event.pos.x - self._press_pos.x
    dy = mouse_event.pos.y - self._press_pos.y

    if self._title_touch_active and self._title_press_pos is not None:
      drag = math.hypot(mouse_event.pos.x - self._title_press_pos.x, mouse_event.pos.y - self._title_press_pos.y)
      if drag > 20:
        self._title_touch_active = False

    if not self._gesture_consumed and abs(dy) > 70 and abs(dy) > abs(dx) * 1.2:
      self._set_selected_game(self._selected_game_idx + (1 if dy < 0 else -1))
      self._gesture_consumed = True
      self._did_long_press = True

  def _handle_mouse_release(self, mouse_pos: MousePos):
    press_drag = 0.0 if self._press_pos is None else math.hypot(mouse_pos.x - self._press_pos.x, mouse_pos.y - self._press_pos.y)

    if self._title_press_pos is not None:
      drag = math.hypot(mouse_pos.x - self._title_press_pos.x, mouse_pos.y - self._title_press_pos.y)
      tapped_title = self._title_touch_active and drag <= 20 and rl.check_collision_point_rec(mouse_pos, self._title_rect())
      self._title_press_pos = None
      self._title_touch_active = False
      if tapped_title:
        self._launch_selected_game()
        self._did_long_press = False
        self._press_pos = None
        self._gesture_consumed = False
        return

    if not self._did_long_press and not self._gesture_consumed and press_drag <= 20:
      if self._on_settings_click:
        self._on_settings_click()
    self._press_pos = None
    self._gesture_consumed = False
    self._did_long_press = False

  def _get_version_text(self) -> tuple[str, str, str, str] | None:
    version = ui_state.params.get("Version")
    branch = ui_state.params.get("GitBranch")
    commit = ui_state.params.get("GitCommit")

    if not all((version, branch, commit)):
      return None

    commit_date_raw = ui_state.params.get("GitCommitDate")
    try:
      # GitCommitDate format from get_commit_date(): '%ct %ci' e.g. "'1708012345 2024-02-15 ...'"
      unix_ts = int(commit_date_raw.strip("'").split()[0])
      date_str = datetime.datetime.fromtimestamp(unix_ts).strftime("%b %d")
    except (ValueError, IndexError, TypeError, AttributeError):
      date_str = ""

    return version, branch, commit[:7], date_str

  def _render(self, _):
    footer_h = 48

    # TODO: why is there extra space here to get it to be flush?
    text_pos = rl.Vector2(self.rect.x - 2 + HOME_PADDING, self.rect.y - 16)
    title_y_offset = 0.0
    incoming_y_offset = 0.0
    progress = min(1.0, max(0.0, (rl.get_time() - self._anim_started_at) / self._anim_duration)) if self._anim_direction else 1.0
    current_alpha = 255
    incoming_alpha = 255
    if self._anim_direction and progress < 1.0:
      travel = 110.0 * (1.0 - (1.0 - progress) * (1.0 - progress))
      title_y_offset = -self._anim_direction * travel
      incoming_y_offset = self._anim_direction * (110.0 - travel)
      current_alpha = max(0, min(255, int(255 * (1.0 - progress))))
      incoming_alpha = max(0, min(255, int(255 * progress)))
    else:
      self._anim_direction = 0

    if self._anim_direction:
      _, prev_text, prev_color = self._game_options[self._anim_from_idx]
      self._doom_label.set_text(prev_text)
      self._doom_label.set_text_color(self._with_alpha(prev_color, current_alpha))
      self._pilot_label.set_text("pilot")
      self._pilot_label.set_text_color(rl.Color(255, 255, 255, current_alpha))
      self._doom_label.set_position(text_pos.x, text_pos.y + title_y_offset)
      self._doom_label.render()
      self._pilot_label.set_position(text_pos.x + self._doom_label.text_width, text_pos.y + title_y_offset)
      self._pilot_label.render()

      _, current_text, current_color = self._game_options[self._selected_game_idx]
      self._incoming_doom_label.set_text(current_text)
      self._incoming_doom_label.set_text_color(self._with_alpha(current_color, incoming_alpha))
      self._incoming_pilot_label.set_text("pilot")
      self._incoming_pilot_label.set_text_color(rl.Color(255, 255, 255, incoming_alpha))
      self._incoming_doom_label.set_position(text_pos.x, text_pos.y + incoming_y_offset)
      self._incoming_doom_label.render()
      self._incoming_pilot_label.set_position(text_pos.x + self._incoming_doom_label.text_width, text_pos.y + incoming_y_offset)
      self._incoming_pilot_label.render()
    else:
      _, current_text, current_color = self._game_options[self._selected_game_idx]
      self._doom_label.set_text(current_text)
      self._doom_label.set_text_color(current_color)
      self._pilot_label.set_text("pilot")
      self._pilot_label.set_text_color(rl.WHITE)
      self._doom_label.set_position(text_pos.x, text_pos.y)
      self._doom_label.render()
      self._pilot_label.set_position(text_pos.x + self._doom_label.text_width, text_pos.y)
      self._pilot_label.render()

    if self._version_text is not None:
      # release branch
      release_branch = self._version_text[1] in RELEASE_BRANCHES
      version_pos = rl.Rectangle(text_pos.x, text_pos.y + self._doom_label.font_size + 16, 100, 44)
      self._version_label.set_text(self._version_text[0])
      self._version_label.set_position(version_pos.x, version_pos.y)
      self._version_label.render()

      self._date_label.set_text(" " + self._version_text[3])
      self._date_label.set_position(version_pos.x + self._version_label.text_width + 10, version_pos.y)
      self._date_label.render()

      self._branch_label.set_max_width(gui_app.width - self._version_label.text_width - self._date_label.text_width - 32)
      self._branch_label.set_text(" " + ("release" if release_branch else self._version_text[1]))
      self._branch_label.set_position(version_pos.x + self._version_label.text_width + self._date_label.text_width + 20, version_pos.y)
      self._branch_label.render()

      if not release_branch:
        # 2nd line
        self._version_commit_label.set_text(self._version_text[2])
        self._version_commit_label.set_position(version_pos.x, version_pos.y + self._date_label.font_size + 7)
        self._version_commit_label.render()

    # ***** Center-aligned bottom section icons *****
    self._experimental_icon.set_visible(self._experimental_mode)
    self._mic_icon.set_visible(ui_state.recording_audio)

    footer_rect = rl.Rectangle(self.rect.x + HOME_PADDING, self.rect.y + self.rect.height - footer_h, self.rect.width - HOME_PADDING, footer_h)
    self._status_bar_layout.render(footer_rect)
