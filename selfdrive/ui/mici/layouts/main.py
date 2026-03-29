import pyray as rl
import cereal.messaging as messaging
from openpilot.selfdrive.ui.layouts.doom import DoomLayout
from openpilot.selfdrive.ui.layouts.dino import DinoLayout
from openpilot.selfdrive.ui.layouts.snake import SnakeLayout
from openpilot.selfdrive.ui.layouts.ui_joystick import ui_joystick
from openpilot.selfdrive.ui.mici.layouts.home import MiciHomeLayout
from openpilot.selfdrive.ui.mici.layouts.settings.settings import SettingsLayout
from openpilot.selfdrive.ui.mici.layouts.offroad_alerts import MiciOffroadAlerts
from openpilot.selfdrive.ui.mici.onroad.augmented_road_view import AugmentedRoadView
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.selfdrive.ui.mici.layouts.onboarding import OnboardingWindow
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller import Scroller
from openpilot.system.ui.lib.application import gui_app


ONROAD_DELAY = 2.5  # seconds


class MiciMainLayout(Scroller):
  def __init__(self):
    super().__init__(snap_items=True, spacing=0, pad=0, scroll_indicator=False, edge_shadows=False)

    self._pm = messaging.PubMaster(['bookmarkButton'])

    self._prev_onroad = False
    self._prev_standstill = False
    self._onroad_time_delay: float | None = None
    self._setup = False
    self._games_scroll_lock_until = 0.0
    self._joystick_next_x = 0.0
    self._joystick_next_y = 0.0

    # Initialize widgets
    self._home_layout = MiciHomeLayout()
    self._games_layout = Scroller(horizontal=False, snap_items=True, spacing=0, pad=0, scroll_indicator=False, edge_shadows=False)
    self._doom_layout = DoomLayout()
    self._dino_layout = DinoLayout()
    self._snake_layout = SnakeLayout()
    self._alerts_layout = MiciOffroadAlerts()
    self._settings_layout = SettingsLayout()
    self._onroad_layout = AugmentedRoadView(bookmark_callback=self._on_bookmark_clicked)

    for widget in (self._home_layout, self._games_layout, self._alerts_layout, self._onroad_layout):
      widget.set_enabled(lambda self=self: self.enabled)

    # Initialize widget rects
    for widget in (self._home_layout, self._games_layout, self._settings_layout, self._alerts_layout, self._onroad_layout):
      # TODO: set parent rect and use it if never passed rect from render (like in Scroller)
      widget.set_rect(rl.Rectangle(0, 0, gui_app.width, gui_app.height))

    self._games_layout._scroller.add_widgets([
      self._home_layout,
    ])
    self._games_layout._scroller.set_reset_scroll_at_show(False)

    self._scroller.add_widgets([
      self._alerts_layout,
      self._games_layout,
      self._onroad_layout,
    ])
    self._scroller.set_reset_scroll_at_show(False)

    # Disable scrolling when onroad is interacting with bookmark
    self._scroller.set_scrolling_enabled(lambda: not self._onroad_layout.is_swiping_left())
    self._games_layout._scroller.set_scrolling_enabled(False)

    # Set callbacks
    self._setup_callbacks()
    ui_joystick.start()

    gui_app.add_nav_stack_tick(self._handle_transitions)
    gui_app.push_widget(self)

    # Start onboarding if terms or training not completed, make sure to push after self
    self._onboarding_window = OnboardingWindow(lambda: gui_app.pop_widgets_to(self))
    if not self._onboarding_window.completed:
      gui_app.push_widget(self._onboarding_window)

  def _setup_callbacks(self):
    self._home_layout.set_callbacks(on_settings=lambda: gui_app.push_widget(self._settings_layout),
                                    on_doom=lambda: self._launch_game(self._doom_layout),
                                    on_dino=lambda: self._launch_game(self._dino_layout),
                                    on_snake=lambda: self._launch_game(self._snake_layout))
    self._doom_layout.set_on_hide_callback(self._restore_last_game_home)
    self._dino_layout.set_on_hide_callback(self._restore_last_game_home)
    self._snake_layout.set_on_hide_callback(self._restore_last_game_home)
    self._onroad_layout.set_click_callback(lambda: self._scroll_to_games(self._home_layout))
    device.add_interactive_timeout_callback(self._on_interactive_timeout)

  def _scroll_outer_to(self, layout: Widget):
    layout_x = int(layout.rect.x)
    self._scroller.scroll_to(layout_x, smooth=True)

  def _scroll_to_games(self, layout: Widget):
    self._scroll_outer_to(self._games_layout)

  def _launch_game(self, game_layout: Widget):
    self._games_scroll_lock_until = float("inf")
    gui_app.push_widget(game_layout)

  def _restore_last_game_home(self):
    self._games_scroll_lock_until = rl.get_time() + 0.35
    self._scroll_to_games(self._home_layout)

  def _render(self, _):
    self._update_joystick()

    if not self._setup:
      if self._alerts_layout.active_alerts() > 0:
        self._scroller.scroll_to(self._alerts_layout.rect.x)
      else:
        self._scroller.scroll_to(self._rect.width)
        self._games_layout._scroller.scroll_to(self._home_layout.rect.y)
      self._setup = True

    # Render
    super()._render(self._rect)

  def _outer_pages(self) -> list[Widget]:
    return [self._alerts_layout, self._games_layout, self._onroad_layout]

  def _current_outer_page_idx(self) -> int:
    current_pos = -self._scroller._scroller.scroll_panel.get_offset()
    pages = self._outer_pages()
    return min(range(len(pages)), key=lambda i: abs(pages[i].rect.x - current_pos))

  def _update_joystick(self):
    active_widget = gui_app.get_active_widget()
    if gui_app.widget_in_stack(self._onboarding_window):
      return

    if active_widget == self:
      self._handle_menu_joystick()
      return

    if active_widget == self._settings_layout and ui_joystick.consume_secondary():
      gui_app.pop_widget()

  def _handle_menu_joystick(self):
    now = rl.get_time()
    menu_x, menu_y = ui_joystick.get_menu_axes()

    if abs(menu_x) >= 0.55 and now >= self._joystick_next_x:
      direction = 1 if menu_x > 0 else -1
      idx = self._current_outer_page_idx()
      next_idx = max(0, min(len(self._outer_pages()) - 1, idx + direction))
      if next_idx != idx:
        self._scroll_outer_to(self._outer_pages()[next_idx])
      self._joystick_next_x = now + 0.18
    elif abs(menu_x) < 0.3:
      self._joystick_next_x = 0.0

    if abs(menu_y) >= 0.55 and now >= self._joystick_next_y and self._current_outer_page_idx() == 1:
      self._home_layout.cycle_selected_game(1 if menu_y < 0 else -1)
      self._joystick_next_y = now + 0.18
    elif abs(menu_y) < 0.3:
      self._joystick_next_y = 0.0

    if ui_joystick.consume_primary() and self._current_outer_page_idx() == 1:
      self._home_layout.launch_selected_game()

    if ui_joystick.consume_secondary():
      if self._current_outer_page_idx() == 1:
        self._scroll_outer_to(self._games_layout)

  def _handle_transitions(self):
    # Don't pop if onboarding
    if gui_app.widget_in_stack(self._onboarding_window):
      return

    if ui_state.started != self._prev_onroad:
      self._prev_onroad = ui_state.started

      # onroad: after delay, pop nav stack and scroll to onroad
      # offroad: immediately scroll to home, but don't pop nav stack (can stay in settings)
      if ui_state.started:
        self._onroad_time_delay = rl.get_time()
      else:
        self._scroll_to_games(self._home_layout)

    # FIXME: these two pops can interrupt user interacting in the settings
    if self._onroad_time_delay is not None and rl.get_time() - self._onroad_time_delay >= ONROAD_DELAY:
      gui_app.pop_widgets_to(self, lambda: self._scroll_outer_to(self._onroad_layout))
      self._onroad_time_delay = None

    # When car leaves standstill, pop nav stack and scroll to onroad
    CS = ui_state.sm["carState"]
    if not CS.standstill and self._prev_standstill:
      gui_app.pop_widgets_to(self, lambda: self._scroll_outer_to(self._onroad_layout))
    self._prev_standstill = CS.standstill

  def _game_active(self) -> bool:
    return gui_app.get_active_widget() in (self._doom_layout, self._dino_layout, self._snake_layout)

  def _on_interactive_timeout(self):
    # Don't pop if onboarding
    if gui_app.widget_in_stack(self._onboarding_window) or self._game_active():
      return

    if ui_state.started:
      # Don't pop if at standstill
      if not ui_state.sm["carState"].standstill:
        gui_app.pop_widgets_to(self, lambda: self._scroll_outer_to(self._onroad_layout))
    else:
      # Screen turns off on timeout offroad, so pop immediately without animation
      gui_app.pop_widgets_to(self, instant=True)
      self._scroll_to_games(self._home_layout)

  def _on_bookmark_clicked(self):
    user_bookmark = messaging.new_message('bookmarkButton')
    user_bookmark.valid = True
    self._pm.send('bookmarkButton', user_bookmark)
