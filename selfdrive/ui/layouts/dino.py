import os
import random

import pyray as rl

from openpilot.system.ui.lib.application import FontWeight, MousePos, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.nav_widget import NavWidget
from openpilot.selfdrive.ui.ui_state import ui_state

GRAVITY = 2200.0
JUMP_VELOCITY = -1200.0
GROUND_MARGIN = 90.0
LAYOUT_DIR = os.path.dirname(__file__)
HOTZ_PATH = os.path.join(LAYOUT_DIR, "hotz.png")


class DinoLayout(NavWidget):
  def __init__(self):
    super().__init__()
    self._font = gui_app.font(FontWeight.BOLD)
    self._hud_font = gui_app.font(FontWeight.MEDIUM)
    self._game_rect = rl.Rectangle(0, 0, 0, 0)
    self._ui_scale = 1.0
    self._hotz_texture = None
    self._hotz_mode = False
    self._last_hotz_refresh = 0.0
    self._reset()

  def hide_event(self):
    self._reset()
    super().hide_event()

  def _reset(self):
    self._dead = False
    self._score = 0.0
    self._speed = 300.0
    self._dino_y = 0.0
    self._dino_vy = 0.0
    self._obstacles: list[dict[str, float]] = []
    self._spawn_timer = 0.8

  def _update_layout_rects(self):
    self._ui_scale = max(0.48, min(1.0, min(self._rect.width / 1920.0, self._rect.height / 1080.0)))
    margin = 14.0 * self._ui_scale
    top = 30.0 * self._ui_scale
    self._game_rect = rl.Rectangle(self._rect.x + margin, self._rect.y + top, self._rect.width - margin * 2, self._rect.height - top - margin)
    if self._dino_y == 0.0:
      self._dino_y = self._ground_y() - self._dino_h()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if not rl.check_collision_point_rec(mouse_pos, self._game_rect):
      return
    if self._dead:
      self._reset()
    else:
      self._jump()

  def _render(self, rect: rl.Rectangle):
    self._refresh_hotz_mode()
    dt = max(1.0 / 120.0, min(1.0 / 20.0, rl.get_frame_time() or (1.0 / 60.0)))
    self._update_sim(dt)

    rl.draw_rectangle_rec(rect, rl.Color(247, 247, 247, 255))
    self._draw_world()
    self._draw_hud()
    if self._dead:
      self._draw_game_over()

  def _refresh_hotz_mode(self, force: bool = False):
    now = rl.get_time()
    if force or now - self._last_hotz_refresh > 0.25:
      self._hotz_mode = ui_state.params.get_bool("HotzMode")
      self._last_hotz_refresh = now
      if self._hotz_mode:
        self._ensure_hotz_texture()

  def _ensure_hotz_texture(self):
    if self._hotz_texture is None and os.path.exists(HOTZ_PATH):
      self._hotz_texture = rl.load_texture(HOTZ_PATH)

  def _update_sim(self, dt: float):
    if rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
      gui_app.pop_widget()
    if rl.is_key_pressed(rl.KeyboardKey.KEY_SPACE) or rl.is_key_pressed(rl.KeyboardKey.KEY_UP):
      if self._dead:
        self._reset()
      else:
        self._jump()

    if self._dead:
      return

    self._score += dt * 100.0
    self._speed += dt * 12.0

    self._dino_vy += GRAVITY * dt
    self._dino_y += self._dino_vy * dt
    if self._dino_y >= self._ground_y() - self._dino_h():
      self._dino_y = self._ground_y() - self._dino_h()
      self._dino_vy = 0.0

    self._spawn_timer -= dt
    if self._spawn_timer <= 0.0:
      self._spawn_obstacle()

    dino_rect = self._dino_rect()
    remaining = []
    for obstacle in self._obstacles:
      obstacle["x"] -= self._speed * dt
      obstacle_rect = self._obstacle_rect(obstacle)
      if obstacle_rect.x + obstacle_rect.width > self._game_rect.x:
        remaining.append(obstacle)
      if rl.check_collision_recs(dino_rect, obstacle_rect):
        self._dead = True
    self._obstacles = remaining

  def _jump(self):
    if self._dino_y >= self._ground_y() - self._dino_h() - 1:
      self._dino_vy = JUMP_VELOCITY * self._ui_scale

  def _spawn_obstacle(self):
    c_h = random.choice([55.0, 72.0, 88.0]) * self._ui_scale
    c_w = c_h if self._hotz_mode else 26.0 * self._ui_scale
    self._obstacles.append({
      "x": self._game_rect.x + self._game_rect.width + random.uniform(0, 80) * self._ui_scale,
      "y": self._ground_y() - c_h,
      "w": c_w,
      "h": c_h,
    })
    self._spawn_timer = random.uniform(0.65, 1.35)

  def _ground_y(self) -> float:
    return self._game_rect.y + self._game_rect.height - GROUND_MARGIN * self._ui_scale

  def _dino_w(self) -> float:
    return 58.0 * self._ui_scale

  def _dino_h(self) -> float:
    return 62.0 * self._ui_scale

  def _dino_rect(self) -> rl.Rectangle:
    x = self._game_rect.x + 100.0 * self._ui_scale
    return rl.Rectangle(x, self._dino_y, self._dino_w(), self._dino_h())

  def _obstacle_rect(self, obstacle: dict[str, float]) -> rl.Rectangle:
    return rl.Rectangle(obstacle["x"], obstacle["y"], obstacle["w"], obstacle["h"])

  def _draw_chrome_dino(self, dino: rl.Rectangle):
    body = rl.Color(40, 40, 40, 255)
    eye = rl.WHITE if not self._dead else rl.Color(255, 120, 120, 255)

    rl.draw_rectangle(int(dino.x + 12 * self._ui_scale), int(dino.y + 14 * self._ui_scale),
                      int(30 * self._ui_scale), int(30 * self._ui_scale), body)
    rl.draw_rectangle(int(dino.x + 32 * self._ui_scale), int(dino.y + 2 * self._ui_scale),
                      int(18 * self._ui_scale), int(22 * self._ui_scale), body)
    rl.draw_rectangle(int(dino.x + 22 * self._ui_scale), int(dino.y + 44 * self._ui_scale),
                      int(26 * self._ui_scale), int(8 * self._ui_scale), body)
    rl.draw_rectangle(int(dino.x + 48 * self._ui_scale), int(dino.y + 22 * self._ui_scale),
                      int(10 * self._ui_scale), int(8 * self._ui_scale), body)
    rl.draw_rectangle(int(dino.x + 50 * self._ui_scale), int(dino.y + 16 * self._ui_scale),
                      int(6 * self._ui_scale), int(10 * self._ui_scale), body)
    rl.draw_rectangle(int(dino.x + 18 * self._ui_scale), int(dino.y + dino.height),
                      int(6 * self._ui_scale), int(16 * self._ui_scale), body)
    rl.draw_rectangle(int(dino.x + 34 * self._ui_scale), int(dino.y + dino.height),
                      int(6 * self._ui_scale), int(16 * self._ui_scale), body)
    rl.draw_rectangle(int(dino.x + 34 * self._ui_scale), int(dino.y + 10 * self._ui_scale),
                      int(3 * self._ui_scale), int(3 * self._ui_scale), eye)

  def _draw_world(self):
    ground_y = self._ground_y()
    rl.draw_line(int(self._game_rect.x), int(ground_y), int(self._game_rect.x + self._game_rect.width), int(ground_y), rl.BLACK)

    # Simple parallax dots
    dot_y = self._game_rect.y + 90.0 * self._ui_scale
    for i in range(8):
      x = self._game_rect.x + ((i * 170 + int(self._score * 2)) % int(self._game_rect.width + 200)) - 100
      rl.draw_circle(int(x), int(dot_y + (i % 3) * 18 * self._ui_scale), max(1, int(3 * self._ui_scale)), rl.Color(180, 180, 180, 255))

    # Dino body
    dino = self._dino_rect()
    self._draw_chrome_dino(dino)

    for obstacle in self._obstacles:
      rect = self._obstacle_rect(obstacle)
      if self._hotz_mode and self._hotz_texture is not None and self._hotz_texture.width > 0 and self._hotz_texture.height > 0:
        src = rl.Rectangle(0, 0, self._hotz_texture.width, self._hotz_texture.height)
        rl.draw_texture_pro(self._hotz_texture, src, rect, rl.Vector2(0, 0), 0.0, rl.WHITE)
        continue
      body = rl.Color(60, 120, 60, 255)
      glow = rl.Color(225, 255, 225, 140)
      rl.draw_rectangle(int(rect.x + rect.width * 0.35), int(rect.y), int(rect.width * 0.3), int(rect.height), body)
      rl.draw_rectangle(int(rect.x), int(rect.y + rect.height * 0.2), int(rect.width * 0.28), int(rect.height * 0.24), body)
      rl.draw_rectangle(int(rect.x + rect.width * 0.72), int(rect.y + rect.height * 0.42), int(rect.width * 0.28), int(rect.height * 0.18), body)
      rl.draw_line(int(rect.x + rect.width * 0.5), int(rect.y), int(rect.x + rect.width * 0.5), int(rect.y + rect.height), glow)

  def _draw_hud(self):
    score_text = f"SCORE {int(self._score):05d}"
    speed_text = f"SPEED {int(self._speed):04d}"
    font_size = 28.0 * self._ui_scale
    rl.draw_text_ex(self._hud_font, "DINOPILOT", rl.Vector2(self._game_rect.x, self._game_rect.y), 34.0 * self._ui_scale, 0, rl.Color(60, 60, 60, 255))

    score_size = measure_text_cached(self._font, score_text, font_size)
    rl.draw_text_ex(self._font, score_text, rl.Vector2(self._game_rect.x + self._game_rect.width - score_size.x, self._game_rect.y + 2.0 * self._ui_scale), font_size, 0, rl.Color(60, 60, 60, 255))
    rl.draw_text_ex(self._hud_font, speed_text, rl.Vector2(self._game_rect.x, self._game_rect.y + 38.0 * self._ui_scale), 22.0 * self._ui_scale, 0, rl.Color(120, 120, 120, 255))

  def _draw_game_over(self):
    text = "TAP TO RUN AGAIN"
    font_size = 38.0 * self._ui_scale
    size = measure_text_cached(self._font, text, font_size)
    x = self._game_rect.x + (self._game_rect.width - size.x) / 2
    y = self._game_rect.y + self._game_rect.height * 0.32
    rl.draw_text_ex(self._font, "GAME OVER", rl.Vector2(x + 4 * self._ui_scale, y - 60 * self._ui_scale), 54.0 * self._ui_scale, 0, rl.Color(40, 40, 40, 255))
    rl.draw_text_ex(self._hud_font, text, rl.Vector2(x, y), font_size, 0, rl.Color(90, 90, 90, 255))
