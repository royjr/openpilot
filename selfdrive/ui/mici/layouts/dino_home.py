import pyray as rl

from openpilot.selfdrive.ui.mici.layouts.home import HOME_PADDING, MiciHomeLayout
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.version import RELEASE_BRANCHES
from openpilot.selfdrive.ui.ui_state import ui_state


class DinoHomeLayout(MiciHomeLayout):
  def __init__(self):
    super().__init__()
    self._on_dino_click = None
    self._doom_label = UnifiedLabel("dino", font_size=96, font_weight=FontWeight.DISPLAY, text_color=rl.Color(80, 170, 80, 255),
                                    max_width=480, wrap_text=False)
    self._pilot_label = UnifiedLabel("pilot", font_size=96, font_weight=FontWeight.DISPLAY, text_color=rl.WHITE,
                                     max_width=480, wrap_text=False)

  def set_callbacks(self, on_settings=None, on_dino=None):
    self._on_settings_click = on_settings
    self._on_dino_click = on_dino
    self._on_doom_click = on_dino

  def _render(self, _):
    footer_h = 48

    text_pos = rl.Vector2(self.rect.x - 2 + HOME_PADDING, self.rect.y - 16)
    self._doom_label.set_position(text_pos.x, text_pos.y)
    self._doom_label.render()
    self._pilot_label.set_position(text_pos.x + self._doom_label.text_width, text_pos.y)
    self._pilot_label.render()

    if self._version_text is not None:
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
        self._version_commit_label.set_text(self._version_text[2])
        self._version_commit_label.set_position(version_pos.x, version_pos.y + self._date_label.font_size + 7)
        self._version_commit_label.render()

    self._experimental_icon.set_visible(self._experimental_mode)
    self._mic_icon.set_visible(ui_state.recording_audio)
    footer_rect = rl.Rectangle(self.rect.x + HOME_PADDING, self.rect.y + self.rect.height - footer_h, self.rect.width - HOME_PADDING, footer_h)
    self._status_bar_layout.render(footer_rect)
