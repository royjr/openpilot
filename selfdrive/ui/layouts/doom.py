import math
import os
from collections.abc import Callable
from dataclasses import dataclass

import pyray as rl

from openpilot.system.ui.lib.application import FontWeight, MouseEvent, MousePos, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.nav_widget import NavWidget
from openpilot.selfdrive.ui.layouts.game_audio import ensure_audio_device
from openpilot.selfdrive.ui.layouts.ui_joystick import ui_joystick
from openpilot.selfdrive.ui.ui_state import ui_state

FOV = math.radians(70.0)
MAX_RAY_DIST = 20.0
PLAYER_RADIUS = 0.18
MOVE_SPEED = 2.7
TURN_SPEED = 2.2
ENEMY_KILL_DIST = 0.55
VIRTUAL_PAD_DEADZONE = 18.0
VIRTUAL_PAD_MAX_RADIUS = 120.0
LAYOUT_DIR = os.path.dirname(__file__)
DOOM_MUSIC_PATH = os.path.join(LAYOUT_DIR, "doom.mp3")
DOOM_DIE_PATH = os.path.join(LAYOUT_DIR, "doom_die.mp3")
HOTZ_PATH = os.path.join(LAYOUT_DIR, "hotz.png")

MAP = [
  "############",
  "#..........#",
  "#.####.###.#",
  "#.#.......##",
  "#.#.###.#..#",
  "#...#...#..#",
  "###.#.###..#",
  "#...#...##.#",
  "#.###.#....#",
  "#.....#.##.#",
  "#..E.......#",
  "############",
]


@dataclass(slots=True)
class Enemy:
  x: float
  y: float
  alive: bool = True

class DoomLayout(NavWidget):
  BACK_TOUCH_AREA_PERCENTAGE = 0.08

  def __init__(self):
    super().__init__()
    self._on_hide: Callable[[], None] | None = None
    self._font = gui_app.font(FontWeight.BOLD)
    self._hud_font = gui_app.font(FontWeight.MEDIUM)

    self._view_rect = rl.Rectangle(0, 0, 0, 0)
    self._hud_rect = rl.Rectangle(0, 0, 0, 0)

    self._music = None
    self._success_sound = None
    self._death_sound = None
    self._audio_loaded = False
    self._hotz_texture = None
    self._hotz_mode = False
    self._last_hotz_refresh = 0.0

    self._flash = 0.0
    self._fire_cooldown = 0.0
    self._message = ""
    self._message_time = 0.0
    self._ui_scale = 1.0
    self._performance_mode = True
    self._touch_origin: list[MousePos | None] = [None, None]
    self._touch_current: list[MousePos | None] = [None, None]
    self._touch_dragged: list[bool] = [False, False]

    self._reset()

  def show_event(self):
    super().show_event()
    self._refresh_hotz_mode(force=True)
    self._ensure_audio_loaded()
    self._ensure_hotz_texture()
    self._start_music()

  def hide_event(self):
    self._stop_music()
    self._reset(restart_music=False)
    if self._on_hide is not None:
      self._on_hide()
    super().hide_event()

  def set_on_hide_callback(self, callback: Callable[[], None] | None):
    self._on_hide = callback

  def _reset(self, restart_music: bool = True):
    self._player_x = 1.5
    self._player_y = 1.5
    self._player_angle = 0.25
    self._kills = 0
    self._win = False
    self._dead = False
    self._elapsed = 0.0
    self._flash = 0.0
    self._fire_cooldown = 0.0
    self._message = "ESCAPE THE MAZE"
    self._message_time = 2.5
    self._enemies = [
      Enemy(5.5, 3.5),
      Enemy(9.2, 6.5),
      Enemy(8.5, 9.0),
    ]
    if restart_music:
      self._start_music()

  def _update_layout_rects(self):
    self._ui_scale = max(0.48, min(1.0, min(self._rect.width / 1920.0, self._rect.height / 1080.0)))
    margin = 12.0 * self._ui_scale
    hud_h = 76.0 * self._ui_scale
    top_h = 96.0 * self._ui_scale
    bottom_h = 0.0
    self._hud_rect = rl.Rectangle(self._rect.x + margin, self._rect.y + margin, self._rect.width - margin * 2, hud_h)
    self._view_rect = rl.Rectangle(self._rect.x + margin, self._rect.y + top_h, self._rect.width - margin * 2, self._rect.height - top_h - bottom_h)

  def _render(self, rect: rl.Rectangle):
    self._refresh_hotz_mode()
    dt = max(1.0 / 120.0, min(1.0 / 20.0, rl.get_frame_time() or (1.0 / 60.0)))
    self._update_sim(dt)
    self._tick_audio()

    rl.draw_rectangle_rec(rect, rl.Color(10, 10, 14, 255))
    self._draw_view()
    self._draw_enemies()
    self._draw_crosshair()
    self._draw_minimap()
    self._draw_hud()
    self._draw_virtual_pad()
    self._draw_overlays()

  def _refresh_hotz_mode(self, force: bool = False):
    now = rl.get_time()
    if force or now - self._last_hotz_refresh > 0.25:
      self._hotz_mode = ui_state.params.get_bool("HotzMode")
      self._last_hotz_refresh = now

  def _ensure_hotz_texture(self):
    if self._hotz_texture is None and os.path.exists(HOTZ_PATH):
      self._hotz_texture = rl.load_texture(HOTZ_PATH)

  def _handle_mouse_event(self, mouse_event: MouseEvent) -> None:
    super()._handle_mouse_event(mouse_event)

    if mouse_event.slot >= len(self._touch_origin):
      return

    if mouse_event.left_pressed and rl.check_collision_point_rec(mouse_event.pos, self._view_rect):
      self._touch_origin[mouse_event.slot] = mouse_event.pos
      self._touch_current[mouse_event.slot] = mouse_event.pos
      self._touch_dragged[mouse_event.slot] = False
    elif mouse_event.left_down and self._touch_origin[mouse_event.slot] is not None:
      self._touch_current[mouse_event.slot] = mouse_event.pos
      drag = math.hypot(mouse_event.pos.x - self._touch_origin[mouse_event.slot].x,
                        mouse_event.pos.y - self._touch_origin[mouse_event.slot].y)
      if drag > VIRTUAL_PAD_DEADZONE * self._ui_scale:
        self._touch_dragged[mouse_event.slot] = True
    elif mouse_event.left_released:
      self._touch_current[mouse_event.slot] = mouse_event.pos

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    release_slot = next((i for i, origin in enumerate(self._touch_origin) if origin is not None), None)
    was_drag = False if release_slot is None else self._touch_dragged[release_slot]

    if rl.check_collision_point_rec(mouse_pos, self._view_rect):
      if self._win or self._dead:
        self._reset()
      elif not was_drag:
        self._fire()

    if release_slot is not None:
      self._touch_origin[release_slot] = None
      self._touch_current[release_slot] = None
      self._touch_dragged[release_slot] = False

  def _update_sim(self, dt: float):
    self._elapsed += dt
    self._flash = max(0.0, self._flash - dt * 2.0)
    self._fire_cooldown = max(0.0, self._fire_cooldown - dt)
    self._message_time = max(0.0, self._message_time - dt)

    turn_dir = 0.0
    move_dir = 0.0
    strafe_dir = 0.0

    if rl.is_key_down(rl.KeyboardKey.KEY_LEFT):
      turn_dir -= 1.0
    if rl.is_key_down(rl.KeyboardKey.KEY_RIGHT):
      turn_dir += 1.0
    if rl.is_key_down(rl.KeyboardKey.KEY_UP) or rl.is_key_down(rl.KeyboardKey.KEY_W):
      move_dir += 1.0
    if rl.is_key_down(rl.KeyboardKey.KEY_DOWN) or rl.is_key_down(rl.KeyboardKey.KEY_S):
      move_dir -= 1.0
    if rl.is_key_down(rl.KeyboardKey.KEY_A):
      strafe_dir -= 1.0
    if rl.is_key_down(rl.KeyboardKey.KEY_D):
      strafe_dir += 1.0
    if rl.is_key_pressed(rl.KeyboardKey.KEY_SPACE):
      self._fire()
    if rl.is_key_pressed(rl.KeyboardKey.KEY_R):
      self._reset()
    if rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
      gui_app.pop_widget()

    touch_move, touch_turn = self._get_virtual_pad_input()
    move_dir += touch_move
    turn_dir += touch_turn

    joy_move, joy_turn = ui_joystick.get_game_axes()
    move_dir += joy_move
    turn_dir += joy_turn

    joy_fire = ui_joystick.consume_primary() or ui_joystick.consume_alt_fire()
    joy_restart = ui_joystick.consume_restart()
    if ui_joystick.consume_secondary():
      gui_app.pop_widget()
    if joy_restart:
      self._reset()
    elif joy_fire:
      if self._win or self._dead:
        self._reset()
      else:
        self._fire()

    move_dir = max(-1.0, min(1.0, move_dir))
    turn_dir = max(-1.0, min(1.0, turn_dir))

    self._player_angle = (self._player_angle + turn_dir * TURN_SPEED * dt) % math.tau
    if not self._win and not self._dead:
      self._try_move(move_dir, strafe_dir, dt)

    if self._tile_at(self._player_x, self._player_y) == "E" and not self._win and not self._dead:
      self._win = True
      self._message = "YOU ESCAPED"
      self._message_time = 99.0
      self._stop_music()
      self._play_success()

    if not self._win and not self._dead:
      self._check_enemy_collision()

  def _try_move(self, move_dir: float, strafe_dir: float, dt: float):
    step = MOVE_SPEED * dt
    dx = math.cos(self._player_angle) * move_dir * step + math.cos(self._player_angle + math.pi / 2) * strafe_dir * step * 0.7
    dy = math.sin(self._player_angle) * move_dir * step + math.sin(self._player_angle + math.pi / 2) * strafe_dir * step * 0.7

    next_x = self._player_x + dx
    next_y = self._player_y + dy
    if not self._blocked(next_x, self._player_y):
      self._player_x = next_x
    if not self._blocked(self._player_x, next_y):
      self._player_y = next_y

  def _blocked(self, x: float, y: float) -> bool:
    checks = [
      (x - PLAYER_RADIUS, y),
      (x + PLAYER_RADIUS, y),
      (x, y - PLAYER_RADIUS),
      (x, y + PLAYER_RADIUS),
    ]
    return any(self._tile_at(px, py) == "#" for px, py in checks)

  def _tile_at(self, x: float, y: float) -> str:
    ix = int(x)
    iy = int(y)
    if iy < 0 or iy >= len(MAP) or ix < 0 or ix >= len(MAP[0]):
      return "#"
    return MAP[iy][ix]

  def _cast_ray(self, angle: float) -> tuple[float, str]:
    dir_x = math.cos(angle)
    dir_y = math.sin(angle)
    map_x = int(self._player_x)
    map_y = int(self._player_y)

    delta_x = abs(1.0 / dir_x) if abs(dir_x) > 1e-6 else float("inf")
    delta_y = abs(1.0 / dir_y) if abs(dir_y) > 1e-6 else float("inf")

    if dir_x < 0:
      step_x = -1
      side_x = (self._player_x - map_x) * delta_x
    else:
      step_x = 1
      side_x = (map_x + 1.0 - self._player_x) * delta_x

    if dir_y < 0:
      step_y = -1
      side_y = (self._player_y - map_y) * delta_y
    else:
      step_y = 1
      side_y = (map_y + 1.0 - self._player_y) * delta_y

    dist = 0.0
    while dist < MAX_RAY_DIST:
      if side_x < side_y:
        map_x += step_x
        dist = side_x
        side_x += delta_x
      else:
        map_y += step_y
        dist = side_y
        side_y += delta_y

      if map_y < 0 or map_y >= len(MAP) or map_x < 0 or map_x >= len(MAP[0]):
        return min(dist, MAX_RAY_DIST), "#"

      tile = MAP[map_y][map_x]
      if tile != ".":
        return min(dist, MAX_RAY_DIST), tile

    return MAX_RAY_DIST, "."

  def _draw_view(self):
    sky = rl.Color(32, 18, 24, 255)
    floor = rl.Color(30, 24, 20, 255)
    rl.draw_rectangle(int(self._view_rect.x), int(self._view_rect.y), int(self._view_rect.width), int(self._view_rect.height / 2), sky)
    rl.draw_rectangle(int(self._view_rect.x), int(self._view_rect.y + self._view_rect.height / 2), int(self._view_rect.width), int(self._view_rect.height / 2), floor)

    stripe_w = max(6 if self._performance_mode else 2, int((8 if self._performance_mode else 4) * self._ui_scale))
    for col in range(0, int(self._view_rect.width), stripe_w):
      ray_angle = self._player_angle - FOV / 2 + (col / max(self._view_rect.width, 1.0)) * FOV
      dist, tile = self._cast_ray(ray_angle)
      corrected_dist = max(0.0001, dist * math.cos(ray_angle - self._player_angle))
      wall_height = min(self._view_rect.height, (self._view_rect.height * 0.92) / corrected_dist)
      wall_y = self._view_rect.y + (self._view_rect.height - wall_height) / 2

      shade = max(30, min(255, int(220 / (1.0 + corrected_dist * 0.22))))
      if tile == "E":
        color = rl.Color(shade, 200, 80, 255)
      else:
        color = rl.Color(shade, max(10, shade // 5), max(10, shade // 6), 255)

      rl.draw_rectangle(int(self._view_rect.x + col), int(wall_y), stripe_w + 1, int(wall_height), color)

  def _draw_enemies(self):
    self._ensure_hotz_texture()
    live = []
    for enemy in self._enemies:
      if not enemy.alive:
        continue
      dx = enemy.x - self._player_x
      dy = enemy.y - self._player_y
      dist = math.hypot(dx, dy)
      angle = math.atan2(dy, dx)
      rel = ((angle - self._player_angle + math.pi) % math.tau) - math.pi
      if abs(rel) > FOV * 0.65:
        continue
      wall_dist, _ = self._cast_ray(angle)
      if wall_dist + 0.05 < dist:
        continue
      live.append((dist, rel, enemy))

    for dist, rel, _enemy in sorted(live, key=lambda item: item[0], reverse=True):
      size = min(180.0 * self._ui_scale, self._view_rect.height / max(dist, 0.1))
      x = self._view_rect.x + (rel + FOV / 2) / FOV * self._view_rect.width
      y = self._view_rect.y + self._view_rect.height / 2 + 25 * self._ui_scale / max(dist, 0.3)
      if self._hotz_mode and self._hotz_texture is not None and self._hotz_texture.width > 0 and self._hotz_texture.height > 0:
        aspect = self._hotz_texture.width / self._hotz_texture.height
        sprite_h = size * 1.28
        sprite_w = sprite_h * aspect
        dest = rl.Rectangle(x - sprite_w / 2, y - sprite_h * 0.72, sprite_w, sprite_h)
        src = rl.Rectangle(0, 0, self._hotz_texture.width, self._hotz_texture.height)
        rl.draw_texture_pro(self._hotz_texture, src, dest, rl.Vector2(0, 0), 0.0, rl.WHITE)
        continue
      body = rl.Color(180, 20, 20, 255)
      glow = rl.Color(255, 80, 20, 170)
      rl.draw_circle_gradient(int(x), int(y - size * 0.15), int(size * 0.42), glow, body)
      rl.draw_circle(int(x - size * 0.12), int(y - size * 0.18), int(size * 0.06), rl.Color(255, 220, 90, 255))
      rl.draw_circle(int(x + size * 0.12), int(y - size * 0.18), int(size * 0.06), rl.Color(255, 220, 90, 255))

  def _draw_crosshair(self):
    cx = self._view_rect.x + self._view_rect.width / 2
    cy = self._view_rect.y + self._view_rect.height / 2
    color = rl.Color(255, 230, 210, 255)
    outer = 18 * self._ui_scale
    inner = 6 * self._ui_scale
    rl.draw_line(int(cx - outer), int(cy), int(cx - inner), int(cy), color)
    rl.draw_line(int(cx + inner), int(cy), int(cx + outer), int(cy), color)
    rl.draw_line(int(cx), int(cy - outer), int(cx), int(cy - inner), color)
    rl.draw_line(int(cx), int(cy + inner), int(cx), int(cy + outer), color)

  def _draw_minimap(self):
    if self._performance_mode:
      return

    scale = max(8, int(16 * self._ui_scale))
    offset = 20.0 * self._ui_scale
    map_rect = rl.Rectangle(self._view_rect.x + offset, self._view_rect.y + offset, len(MAP[0]) * scale, len(MAP) * scale)
    rl.draw_rectangle_rec(map_rect, rl.Color(0, 0, 0, 160))

    for y, row in enumerate(MAP):
      for x, tile in enumerate(row):
        color = rl.Color(35, 35, 35, 255)
        if tile == "#":
          color = rl.Color(155, 40, 40, 255)
        elif tile == "E":
          color = rl.Color(50, 180, 80, 255)
        rl.draw_rectangle(int(map_rect.x + x * scale), int(map_rect.y + y * scale), scale - 1, scale - 1, color)

    for enemy in self._enemies:
      if enemy.alive:
        rl.draw_circle(int(map_rect.x + enemy.x * scale), int(map_rect.y + enemy.y * scale), max(2, int(4 * self._ui_scale)), rl.Color(255, 210, 60, 255))

    px = map_rect.x + self._player_x * scale
    py = map_rect.y + self._player_y * scale
    rl.draw_circle(int(px), int(py), max(2, int(4 * self._ui_scale)), rl.WHITE)
    rl.draw_line(int(px), int(py), int(px + math.cos(self._player_angle) * 12 * self._ui_scale), int(py + math.sin(self._player_angle) * 12 * self._ui_scale), rl.WHITE)

  def _draw_hud(self):
    rl.draw_rectangle_rounded(self._hud_rect, 0.22, 12, rl.Color(15, 0, 0, 190))
    title_font = (34 if self._performance_mode else 42) * self._ui_scale
    text = f"KILLS {self._kills:02d}/{len(self._enemies):02d}"
    rl.draw_text_ex(self._font, text, rl.Vector2(self._hud_rect.x + 30 * self._ui_scale, self._hud_rect.y + 22 * self._ui_scale), title_font, 0, rl.Color(255, 220, 210, 255))

    time_text = f"TIME {self._elapsed:05.1f}"
    time_size = measure_text_cached(self._font, time_text, title_font)
    rl.draw_text_ex(self._font, time_text, rl.Vector2(self._hud_rect.x + self._hud_rect.width - time_size.x - 30 * self._ui_scale, self._hud_rect.y + 22 * self._ui_scale), title_font, 0, rl.Color(255, 220, 210, 255))

    joy_text = self._joystick_status_text()
    joy_font = (18 if self._performance_mode else 22) * self._ui_scale
    joy_color = rl.Color(120, 220, 140, 255) if "ON" in joy_text else rl.Color(180, 180, 180, 220)
    rl.draw_text_ex(self._hud_font, joy_text, rl.Vector2(self._hud_rect.x + 30 * self._ui_scale, self._hud_rect.y + self._hud_rect.height - 28 * self._ui_scale), joy_font, 0, joy_color)

  def _joystick_status_text(self) -> str:
    if not ui_joystick.enabled:
      return "PAD OFF"
    return "PAD ON" if ui_joystick.connected else "PAD WAIT"

  def _get_virtual_pad_input(self) -> tuple[float, float]:
    for slot in range(len(self._touch_origin)):
      origin = self._touch_origin[slot]
      current = self._touch_current[slot]
      if origin is None or current is None:
        continue

      dx = current.x - origin.x
      dy = current.y - origin.y
      radius = VIRTUAL_PAD_MAX_RADIUS * self._ui_scale
      dist = math.hypot(dx, dy)
      if dist < VIRTUAL_PAD_DEADZONE * self._ui_scale:
        return 0.0, 0.0

      scale = min(1.0, dist / radius)
      turn = max(-1.0, min(1.0, dx / radius)) * scale
      move = max(-1.0, min(1.0, -dy / radius)) * scale
      return move, turn

    return 0.0, 0.0

  def _draw_virtual_pad(self):
    for slot in range(len(self._touch_origin)):
      origin = self._touch_origin[slot]
      current = self._touch_current[slot]
      if origin is None or current is None:
        continue

      radius = VIRTUAL_PAD_MAX_RADIUS * self._ui_scale
      knob_radius = 34 * self._ui_scale
      dx = current.x - origin.x
      dy = current.y - origin.y
      dist = math.hypot(dx, dy)
      if dist > radius and dist > 0:
        dx *= radius / dist
        dy *= radius / dist

      base_color = rl.Color(255, 255, 255, 45)
      edge_color = rl.Color(255, 255, 255, 90)
      knob_color = rl.Color(255, 80, 80, 180)
      rl.draw_circle(int(origin.x), int(origin.y), radius, base_color)
      rl.draw_circle_lines(int(origin.x), int(origin.y), radius, edge_color)
      rl.draw_circle(int(origin.x + dx), int(origin.y + dy), knob_radius, knob_color)

  def _draw_overlays(self):
    if self._flash > 0.0:
      alpha = int(110 * self._flash)
      rl.draw_rectangle_rec(self._view_rect, rl.Color(255, 210, 170, alpha))

    if self._message_time > 0.0:
      font_size = 68 * self._ui_scale
      size = measure_text_cached(self._font, self._message, font_size)
      x = self._view_rect.x + (self._view_rect.width - size.x) / 2
      y = self._view_rect.y + 28 * self._ui_scale
      rl.draw_text_ex(self._font, self._message, rl.Vector2(x, y), font_size, 0, rl.Color(255, 230, 210, 255))

    if self._win or self._dead:
      msg = "TAP THE SCREEN FOR ANOTHER RUN"
      hint_font = 34 * self._ui_scale
      size = measure_text_cached(self._hud_font, msg, hint_font)
      x = self._view_rect.x + (self._view_rect.width - size.x) / 2
      y = self._view_rect.y + self._view_rect.height - 56 * self._ui_scale
      rl.draw_text_ex(self._hud_font, msg, rl.Vector2(x, y), hint_font, 0, rl.Color(255, 220, 180, 255))

  def _fire(self):
    if self._fire_cooldown > 0.0 or self._dead:
      return

    self._fire_cooldown = 0.25
    self._flash = 1.0
    best_enemy = None
    best_dist = 999.0

    for enemy in self._enemies:
      if not enemy.alive:
        continue
      dx = enemy.x - self._player_x
      dy = enemy.y - self._player_y
      dist = math.hypot(dx, dy)
      angle = math.atan2(dy, dx)
      rel = abs(((angle - self._player_angle + math.pi) % math.tau) - math.pi)
      wall_dist, _ = self._cast_ray(angle)
      if rel < math.radians(8) and dist < best_dist and wall_dist + 0.05 >= dist:
        best_dist = dist
        best_enemy = enemy

    if best_enemy is not None:
      best_enemy.alive = False
      self._kills += 1
      self._message = "DIRECT HIT"
      self._message_time = 0.6

  def _check_enemy_collision(self):
    for enemy in self._enemies:
      if enemy.alive and math.hypot(enemy.x - self._player_x, enemy.y - self._player_y) < ENEMY_KILL_DIST:
        self._dead = True
        self._message = "YOU DIED"
        self._message_time = 99.0
        self._stop_music()
        self._play_death()
        return

  def _ensure_audio_loaded(self):
    if self._audio_loaded:
      return

    ensure_audio_device(rl)
    self._music = rl.load_music_stream(DOOM_MUSIC_PATH)
    self._death_sound = rl.load_sound(DOOM_DIE_PATH)
    self._success_sound = None
    rl.set_music_volume(self._music, 0.55)
    rl.set_sound_volume(self._death_sound, 0.75)
    self._audio_loaded = True

  def _tick_audio(self):
    if self._audio_loaded and self._music is not None:
      rl.update_music_stream(self._music)
      if not self._win and not self._dead and not rl.is_music_stream_playing(self._music):
        rl.play_music_stream(self._music)

  def _start_music(self):
    if not self._audio_loaded:
      return
    rl.stop_music_stream(self._music)
    rl.play_music_stream(self._music)

  def _stop_music(self):
    if self._audio_loaded and self._music is not None:
      rl.stop_music_stream(self._music)

  def _play_success(self):
    if self._audio_loaded and self._success_sound is not None:
      rl.play_sound(self._success_sound)

  def _play_death(self):
    if self._audio_loaded and self._death_sound is not None:
      rl.play_sound(self._death_sound)
