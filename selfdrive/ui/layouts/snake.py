import os
import random
from collections.abc import Callable

import pyray as rl

from openpilot.selfdrive.ui.layouts.game_audio import ensure_audio_device
from openpilot.system.ui.lib.application import FontWeight, MousePos, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.nav_widget import NavWidget
from openpilot.selfdrive.ui.ui_state import ui_state

PURPLE = rl.Color(176, 96, 255, 255)
WHITE = rl.Color(245, 245, 245, 255)
BLACK = rl.Color(8, 8, 8, 255)
LAYOUT_DIR = os.path.dirname(__file__)
HOTZ_PATH = os.path.join(LAYOUT_DIR, "hotz.png")
SNAKE_MUSIC_PATH = os.path.join(LAYOUT_DIR, "snake.mp3")


class SnakeLayout(NavWidget):
  def __init__(self):
    super().__init__()
    self._on_hide: Callable[[], None] | None = None
    self._font = gui_app.font(FontWeight.BOLD)
    self._hud_font = gui_app.font(FontWeight.MEDIUM)
    self._hud_rect = rl.Rectangle(0, 0, 0, 0)
    self._view_rect = rl.Rectangle(0, 0, 0, 0)
    self._ui_scale = 1.0
    self._hotz_texture = None
    self._hotz_mode = False
    self._last_hotz_refresh = 0.0
    self._music = None
    self._audio_loaded = False
    self._grid_cols = 0
    self._grid_rows = 0
    self._cell_w = 0.0
    self._cell_h = 0.0
    self._elapsed = 0.0
    self._tick_timer = 0.0
    self._reset()

  def show_event(self):
    super().show_event()
    self._ensure_audio_loaded()
    self._start_music()

  def hide_event(self):
    self._stop_music()
    self._reset()
    if self._on_hide is not None:
      self._on_hide()
    super().hide_event()

  def set_on_hide_callback(self, callback: Callable[[], None] | None):
    self._on_hide = callback

  def _reset(self):
    start_x = max(3, self._grid_cols // 2) if self._grid_cols else 8
    start_y = max(2, self._grid_rows // 2) if self._grid_rows else 13
    self._snake = [(start_x, start_y), (start_x - 1, start_y), (start_x - 2, start_y)]
    self._direction = (1, 0)
    self._pending_direction = (1, 0)
    self._food = (min(start_x + 4, max(0, self._grid_cols - 1)) if self._grid_cols else 12, start_y)
    self._dead = False
    self._elapsed = 0.0
    self._tick_timer = 0.0
    self._score = 0
    self._speed = 7.0
    self._spawn_food()

  def _update_layout_rects(self):
    self._ui_scale = max(0.48, min(1.0, min(self._rect.width / 1920.0, self._rect.height / 1080.0)))
    margin = 12.0 * self._ui_scale
    hud_h = 76.0 * self._ui_scale
    top_h = 96.0 * self._ui_scale
    self._hud_rect = rl.Rectangle(self._rect.x + margin, self._rect.y + margin, self._rect.width - margin * 2, hud_h)
    self._view_rect = rl.Rectangle(self._rect.x + margin, self._rect.y + top_h, self._rect.width - margin * 2, self._rect.height - top_h)
    old_cols, old_rows = self._grid_cols, self._grid_rows
    self._grid_rows = 4
    self._cell_h = max(1.0, self._view_rect.height / self._grid_rows)
    self._cell_w = self._cell_h
    self._grid_cols = max(12, int(self._view_rect.width // self._cell_w))
    if old_cols != self._grid_cols or old_rows != self._grid_rows:
      self._reset()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if not rl.check_collision_point_rec(mouse_pos, self._view_rect):
      return
    if self._dead:
      self._reset()
      return

    center = rl.Vector2(self._view_rect.x + self._view_rect.width / 2, self._view_rect.y + self._view_rect.height / 2)
    dx = mouse_pos.x - center.x
    dy = mouse_pos.y - center.y
    if abs(dx) > abs(dy):
      self._set_direction((1, 0) if dx > 0 else (-1, 0))
    else:
      self._set_direction((0, 1) if dy > 0 else (0, -1))

  def _render(self, rect: rl.Rectangle):
    self._refresh_hotz_mode()
    dt = max(1.0 / 120.0, min(1.0 / 20.0, rl.get_frame_time() or (1.0 / 60.0)))
    self._update_sim(dt)
    self._tick_audio()

    rl.draw_rectangle_rec(rect, BLACK)
    self._draw_world()
    self._draw_hud()
    if self._dead:
      self._draw_game_over()

  def _refresh_hotz_mode(self, force: bool = False):
    now = rl.get_time()
    if force or now - self._last_hotz_refresh > 0.25:
      self._hotz_mode = ui_state.params.get_bool("HotzMode")
      self._last_hotz_refresh = now
      if self._hotz_mode and self._hotz_texture is None:
        self._hotz_texture = rl.load_texture(HOTZ_PATH)

  def _ensure_audio_loaded(self):
    if self._audio_loaded:
      return

    ensure_audio_device(rl)
    self._music = rl.load_music_stream(SNAKE_MUSIC_PATH)
    rl.set_music_volume(self._music, 0.55)
    self._audio_loaded = True

  def _tick_audio(self):
    if self._audio_loaded and self._music is not None:
      rl.update_music_stream(self._music)
      if not rl.is_music_stream_playing(self._music):
        rl.play_music_stream(self._music)

  def _start_music(self):
    if self._audio_loaded and self._music is not None:
      rl.stop_music_stream(self._music)
      rl.play_music_stream(self._music)

  def _stop_music(self):
    if self._audio_loaded and self._music is not None:
      rl.stop_music_stream(self._music)

  def _update_sim(self, dt: float):
    if rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
      gui_app.pop_widget()
    if rl.is_key_pressed(rl.KeyboardKey.KEY_LEFT) or rl.is_key_pressed(rl.KeyboardKey.KEY_A):
      self._set_direction((-1, 0))
    if rl.is_key_pressed(rl.KeyboardKey.KEY_RIGHT) or rl.is_key_pressed(rl.KeyboardKey.KEY_D):
      self._set_direction((1, 0))
    if rl.is_key_pressed(rl.KeyboardKey.KEY_UP) or rl.is_key_pressed(rl.KeyboardKey.KEY_W):
      self._set_direction((0, -1))
    if rl.is_key_pressed(rl.KeyboardKey.KEY_DOWN) or rl.is_key_pressed(rl.KeyboardKey.KEY_S):
      self._set_direction((0, 1))
    if rl.is_key_pressed(rl.KeyboardKey.KEY_SPACE) and self._dead:
      self._reset()

    if self._dead:
      return

    self._elapsed += dt
    self._tick_timer += dt
    tick_interval = 1.0 / self._speed
    while self._tick_timer >= tick_interval:
      self._tick_timer -= tick_interval
      self._advance()

  def _set_direction(self, direction: tuple[int, int]):
    if direction[0] == -self._direction[0] and direction[1] == -self._direction[1]:
      return
    self._pending_direction = direction

  def _advance(self):
    self._direction = self._pending_direction
    head_x, head_y = self._snake[0]
    new_head = ((head_x + self._direction[0]) % self._grid_cols, (head_y + self._direction[1]) % self._grid_rows)
    if new_head in self._snake[:-1]:
      self._dead = True
      return

    self._snake.insert(0, new_head)
    if new_head == self._food:
      self._score += 1
      self._speed = min(14.0, self._speed + 0.45)
      self._spawn_food()
    else:
      self._snake.pop()

  def _spawn_food(self):
    open_cells = [(x, y) for x in range(self._grid_cols) for y in range(self._grid_rows) if (x, y) not in self._snake]
    self._food = random.choice(open_cells) if open_cells else self._food

  def _cell_rect(self, cell: tuple[int, int]) -> rl.Rectangle:
    grid_w = self._grid_cols * self._cell_w
    grid_h = self._grid_rows * self._cell_h
    origin_x = self._view_rect.x + (self._view_rect.width - grid_w) / 2
    origin_y = self._view_rect.y + (self._view_rect.height - grid_h) / 2
    pad_x = max(0.0, self._cell_w * 0.08)
    pad_y = max(0.0, self._cell_h * 0.08)
    x, y = cell
    return rl.Rectangle(origin_x + x * self._cell_w + pad_x, origin_y + y * self._cell_h + pad_y,
                        self._cell_w - pad_x * 2, self._cell_h - pad_y * 2)

  def _draw_world(self):
    grid_w = self._grid_cols * self._cell_w
    grid_h = self._grid_rows * self._cell_h
    grid_x = self._view_rect.x + (self._view_rect.width - grid_w) / 2
    grid_y = self._view_rect.y + (self._view_rect.height - grid_h) / 2
    rl.draw_rectangle_rounded(rl.Rectangle(grid_x, grid_y, grid_w, grid_h), 0.035, 8, rl.Color(24, 12, 36, 255))

    for y in range(self._grid_rows):
      for x in range(self._grid_cols):
        if (x + y) % 2 == 0:
          rect = self._cell_rect((x, y))
          rl.draw_rectangle_rounded(rect, 0.18, 4, rl.Color(42, 24, 64, 180))

    food_rect = self._cell_rect(self._food)
    if self._hotz_mode and self._hotz_texture is not None and self._hotz_texture.width > 0 and self._hotz_texture.height > 0:
      src = rl.Rectangle(0, 0, self._hotz_texture.width, self._hotz_texture.height)
      rl.draw_texture_pro(self._hotz_texture, src, food_rect, rl.Vector2(0, 0), 0.0, rl.WHITE)
    else:
      rl.draw_rectangle_rounded(food_rect, 0.3, 6, PURPLE)

    for idx, cell in enumerate(self._snake):
      rect = self._cell_rect(cell)
      color = WHITE if idx == 0 else rl.Color(210, 180, 255, 255)
      rl.draw_rectangle_rounded(rect, 0.28, 6, color)

  def _draw_hud(self):
    score_text = f"LENGTH {len(self._snake):02d}"
    speed_text = f"SPEED {self._speed:04.1f}"
    stat_font = 34.0 * self._ui_scale
    sub_font = 18.0 * self._ui_scale
    rl.draw_rectangle_rounded(self._hud_rect, 0.22, 12, rl.Color(28, 0, 42, 210))
    rl.draw_text_ex(self._font, score_text, rl.Vector2(self._hud_rect.x + 30 * self._ui_scale, self._hud_rect.y + 22 * self._ui_scale), stat_font, 0, WHITE)

    speed_size = measure_text_cached(self._font, speed_text, stat_font)
    rl.draw_text_ex(self._font, speed_text,
                    rl.Vector2(self._hud_rect.x + self._hud_rect.width - speed_size.x - 30 * self._ui_scale, self._hud_rect.y + 22 * self._ui_scale),
                    stat_font, 0, WHITE)

    rl.draw_text_ex(self._hud_font, "SNAKEPILOT",
                    rl.Vector2(self._hud_rect.x + 30 * self._ui_scale, self._hud_rect.y + self._hud_rect.height - 28 * self._ui_scale),
                    sub_font, 0, PURPLE)
    time_text = f"TIME {self._elapsed:05.1f}"
    time_size = measure_text_cached(self._hud_font, time_text, sub_font)
    rl.draw_text_ex(self._hud_font, time_text,
                    rl.Vector2(self._hud_rect.x + self._hud_rect.width - time_size.x - 30 * self._ui_scale, self._hud_rect.y + self._hud_rect.height - 28 * self._ui_scale),
                    sub_font, 0, rl.Color(214, 180, 255, 255))

  def _draw_game_over(self):
    text = "TAP TO SLITHER AGAIN"
    font_size = 38.0 * self._ui_scale
    size = measure_text_cached(self._font, text, font_size)
    x = self._view_rect.x + (self._view_rect.width - size.x) / 2
    y = self._view_rect.y + self._view_rect.height * 0.32
    rl.draw_text_ex(self._font, "GAME OVER", rl.Vector2(x + 4 * self._ui_scale, y - 60 * self._ui_scale), 54.0 * self._ui_scale, 0, WHITE)
    rl.draw_text_ex(self._hud_font, text, rl.Vector2(x, y), font_size, 0, PURPLE)
