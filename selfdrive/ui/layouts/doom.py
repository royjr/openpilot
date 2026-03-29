import math
import os
import struct
import tempfile
import wave
from dataclasses import dataclass

import pyray as rl

from openpilot.system.ui.lib.application import FontWeight, MousePos, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import Button, ButtonStyle

FOV = math.radians(70.0)
MAX_RAY_DIST = 20.0
PLAYER_RADIUS = 0.18
MOVE_SPEED = 2.7
TURN_SPEED = 2.2
ENEMY_KILL_DIST = 0.55

AUDIO_DIR = os.path.join(tempfile.gettempdir(), "openpilot_doom_audio")

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


_AUDIO_READY = False
_AUDIO_FILES_READY = False


def _square_sample(phase: float) -> float:
  return 1.0 if math.sin(phase) >= 0.0 else -1.0


def _write_wav(path: str, samples: list[float], sample_rate: int = 22050):
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with wave.open(path, "wb") as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(sample_rate)
    frames = bytearray()
    for sample in samples:
      clamped = max(-1.0, min(1.0, sample))
      frames.extend(struct.pack("<h", int(clamped * 32767)))
    wav_file.writeframes(bytes(frames))


def _synth_tone(freq: float, duration: float, volume: float = 0.35, sample_rate: int = 22050,
                wave_fn=_square_sample, tremolo: float = 0.0, decay: float = 0.998) -> list[float]:
  count = max(1, int(duration * sample_rate))
  samples: list[float] = []
  phase = 0.0
  step = math.tau * freq / sample_rate
  amp = volume
  for i in range(count):
    env = amp * (1.0 - i / count) * 0.7 + amp * 0.3
    mod = 1.0 + tremolo * math.sin(i / sample_rate * math.tau * 6.0)
    samples.append(wave_fn(phase) * env * mod)
    phase += step
    amp *= decay
  return samples


def _synth_music(path: str):
  sample_rate = 22050
  melody = [
    (164.81, 0.18), (164.81, 0.18), (196.00, 0.18), (220.00, 0.18),
    (164.81, 0.18), (146.83, 0.18), (130.81, 0.22), (146.83, 0.18),
    (164.81, 0.18), (164.81, 0.18), (196.00, 0.18), (246.94, 0.18),
    (220.00, 0.18), (196.00, 0.18), (164.81, 0.26), (130.81, 0.22),
  ]
  bass = [82.41, 98.00, 73.42, 98.00] * 4
  samples: list[float] = []
  for i, (freq, duration) in enumerate(melody):
    lead = _synth_tone(freq, duration, volume=0.18, sample_rate=sample_rate, tremolo=0.10)
    bass_note = bass[i % len(bass)]
    bass_wave = _synth_tone(bass_note, duration, volume=0.12, sample_rate=sample_rate, wave_fn=math.sin, decay=0.9994)
    mixed = [lead[j] + bass_wave[j] for j in range(min(len(lead), len(bass_wave)))]
    gap = int(sample_rate * 0.01)
    samples.extend(mixed)
    samples.extend([0.0] * gap)
  _write_wav(path, samples, sample_rate)


def _synth_success(path: str):
  sample_rate = 22050
  notes = [(392.00, 0.10), (523.25, 0.10), (659.25, 0.20), (783.99, 0.28)]
  samples: list[float] = []
  for freq, duration in notes:
    samples.extend(_synth_tone(freq, duration, volume=0.24, sample_rate=sample_rate, wave_fn=math.sin, tremolo=0.04, decay=0.9992))
  _write_wav(path, samples, sample_rate)


def _synth_death(path: str):
  sample_rate = 22050
  samples: list[float] = []
  for idx, freq in enumerate([220.00, 207.65, 196.00, 174.61, 146.83, 110.00]):
    duration = 0.08 if idx < 4 else 0.16
    samples.extend(_synth_tone(freq, duration, volume=0.28, sample_rate=sample_rate, tremolo=0.02, decay=0.997))
  _write_wav(path, samples, sample_rate)


def _ensure_audio_files():
  global _AUDIO_FILES_READY
  if _AUDIO_FILES_READY:
    return

  _synth_music(os.path.join(AUDIO_DIR, "start_music.wav"))
  _synth_success(os.path.join(AUDIO_DIR, "success.wav"))
  _synth_death(os.path.join(AUDIO_DIR, "death.wav"))
  _AUDIO_FILES_READY = True


class DoomLayout(Widget):
  def __init__(self):
    super().__init__()
    self._font = gui_app.font(FontWeight.BOLD)
    self._hud_font = gui_app.font(FontWeight.MEDIUM)

    self._exit_button = self._child(Button("X", gui_app.pop_widget, font_size=28))
    self._restart_button = self._child(Button("R", self._reset, button_style=ButtonStyle.DANGER, font_size=28))

    self._view_rect = rl.Rectangle(0, 0, 0, 0)
    self._hud_rect = rl.Rectangle(0, 0, 0, 0)
    self._turn_left_rect = rl.Rectangle(0, 0, 0, 0)
    self._turn_right_rect = rl.Rectangle(0, 0, 0, 0)
    self._forward_rect = rl.Rectangle(0, 0, 0, 0)
    self._back_rect = rl.Rectangle(0, 0, 0, 0)
    self._fire_rect = rl.Rectangle(0, 0, 0, 0)

    self._music = None
    self._success_sound = None
    self._death_sound = None
    self._audio_loaded = False

    self._flash = 0.0
    self._fire_cooldown = 0.0
    self._message = ""
    self._message_time = 0.0
    self._ui_scale = 1.0

    self._reset()

  def show_event(self):
    super().show_event()
    self._ensure_audio_loaded()
    self._start_music()

  def hide_event(self):
    self._stop_music()
    super().hide_event()

  def _reset(self):
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
    self._start_music()

  def _update_layout_rects(self):
    self._ui_scale = max(0.48, min(1.0, min(self._rect.width / 1920.0, self._rect.height / 1080.0)))
    margin = 26.0 * self._ui_scale
    hud_h = 100.0 * self._ui_scale
    top_h = 128.0 * self._ui_scale
    bottom_h = 170.0 * self._ui_scale
    self._hud_rect = rl.Rectangle(self._rect.x + margin, self._rect.y + margin, self._rect.width - margin * 2, hud_h)
    self._view_rect = rl.Rectangle(self._rect.x + margin, self._rect.y + top_h, self._rect.width - margin * 2, self._rect.height - top_h - bottom_h)

    control_y = self._rect.y + self._rect.height - (118.0 * self._ui_scale)
    control_h = 78.0 * self._ui_scale
    control_w = 110.0 * self._ui_scale
    gap = 14.0 * self._ui_scale

    self._turn_left_rect = rl.Rectangle(self._rect.x + margin, control_y, control_w, control_h)
    self._turn_right_rect = rl.Rectangle(self._turn_left_rect.x + control_w + gap, control_y, control_w, control_h)
    self._back_rect = rl.Rectangle(self._rect.x + self._rect.width - margin - control_w * 2 - gap, control_y, control_w, control_h)
    self._forward_rect = rl.Rectangle(self._back_rect.x + control_w + gap, control_y, control_w, control_h)
    fire_w = 120.0 * self._ui_scale
    fire_h = 92.0 * self._ui_scale
    self._fire_rect = rl.Rectangle(self._rect.x + self._rect.width / 2 - fire_w / 2, control_y - 8.0 * self._ui_scale, fire_w, fire_h)

  def _render(self, rect: rl.Rectangle):
    dt = max(1.0 / 120.0, min(1.0 / 20.0, rl.get_frame_time() or (1.0 / 60.0)))
    self._update_sim(dt)
    self._tick_audio()

    rl.draw_rectangle_rec(rect, rl.Color(10, 10, 14, 255))
    self._draw_view()
    self._draw_enemies()
    self._draw_crosshair()
    self._draw_minimap()
    self._draw_hud()
    self._draw_controls()
    self._draw_overlays()

    top_btn_w = 72.0 * self._ui_scale
    top_btn_h = 56.0 * self._ui_scale
    top_gap = 12.0 * self._ui_scale
    top_y = self._rect.y + 22.0 * self._ui_scale
    self._exit_button.render(rl.Rectangle(self._rect.x + self._rect.width - top_btn_w - 40.0 * self._ui_scale, top_y, top_btn_w, top_btn_h))
    self._restart_button.render(rl.Rectangle(self._rect.x + self._rect.width - top_btn_w * 2 - top_gap - 40.0 * self._ui_scale, top_y, top_btn_w, top_btn_h))

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if rl.check_collision_point_rec(mouse_pos, self._fire_rect) or rl.check_collision_point_rec(mouse_pos, self._view_rect):
      self._fire()

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

    for slot in range(2):
      if not rl.is_mouse_button_down(slot):
        continue
      pos = rl.get_touch_position(slot)
      if pos.x == 0 and pos.y == 0 and slot > 0:
        continue
      if rl.check_collision_point_rec(pos, self._turn_left_rect):
        turn_dir -= 1.0
      elif rl.check_collision_point_rec(pos, self._turn_right_rect):
        turn_dir += 1.0
      elif rl.check_collision_point_rec(pos, self._forward_rect):
        move_dir += 1.0
      elif rl.check_collision_point_rec(pos, self._back_rect):
        move_dir -= 1.0

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
    ray_x = self._player_x
    ray_y = self._player_y
    step = 0.02
    dist = 0.0
    while dist < MAX_RAY_DIST:
      ray_x += math.cos(angle) * step
      ray_y += math.sin(angle) * step
      dist += step
      tile = self._tile_at(ray_x, ray_y)
      if tile != ".":
        return dist, tile
    return MAX_RAY_DIST, "."

  def _draw_view(self):
    sky = rl.Color(32, 18, 24, 255)
    floor = rl.Color(30, 24, 20, 255)
    rl.draw_rectangle(int(self._view_rect.x), int(self._view_rect.y), int(self._view_rect.width), int(self._view_rect.height / 2), sky)
    rl.draw_rectangle(int(self._view_rect.x), int(self._view_rect.y + self._view_rect.height / 2), int(self._view_rect.width), int(self._view_rect.height / 2), floor)

    stripe_w = max(2, int(4 * self._ui_scale))
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
    rl.draw_rectangle_rounded(self._hud_rect, 0.22, 12, rl.Color(15, 0, 0, 210))
    title_font = 42 * self._ui_scale
    sub_font = 28 * self._ui_scale
    text = f"KILLS {self._kills:02d}/{len(self._enemies):02d}"
    rl.draw_text_ex(self._font, text, rl.Vector2(self._hud_rect.x + 30 * self._ui_scale, self._hud_rect.y + 22 * self._ui_scale), title_font, 0, rl.Color(255, 220, 210, 255))

    time_text = f"TIME {self._elapsed:05.1f}"
    time_size = measure_text_cached(self._font, time_text, title_font)
    rl.draw_text_ex(self._font, time_text, rl.Vector2(self._hud_rect.x + self._hud_rect.width - time_size.x - 30 * self._ui_scale, self._hud_rect.y + 22 * self._ui_scale), title_font, 0, rl.Color(255, 220, 210, 255))

    subtitle = "WASD/ARROWS OR TOUCH PADS"
    if self._dead:
      subtitle = "YOU DIED"
    elif self._win:
      subtitle = "ESCAPE COMPLETE"
    rl.draw_text_ex(self._hud_font, subtitle, rl.Vector2(self._hud_rect.x + 32 * self._ui_scale, self._hud_rect.y + 66 * self._ui_scale), sub_font, 0, rl.Color(255, 180, 160, 255))

  def _draw_controls(self):
    base_font = 28 * self._ui_scale
    self._draw_control(self._turn_left_rect, "<", rl.Color(60, 20, 20, 255), font_size=base_font)
    self._draw_control(self._turn_right_rect, ">", rl.Color(60, 20, 20, 255), font_size=base_font)
    self._draw_control(self._back_rect, "v", rl.Color(45, 30, 30, 255), font_size=base_font)
    self._draw_control(self._forward_rect, "^", rl.Color(45, 30, 30, 255), font_size=base_font)
    self._draw_control(self._fire_rect, "*", rl.Color(110, 20, 20, 255), font_size=34 * self._ui_scale)

  def _draw_control(self, rect: rl.Rectangle, label: str, bg: rl.Color, font_size: float = 40):
    active = False
    for slot in range(2):
      if rl.is_mouse_button_down(slot) and rl.check_collision_point_rec(rl.get_touch_position(slot), rect):
        active = True
        break
    color = rl.Color(min(255, bg.r + 35), min(255, bg.g + 20), min(255, bg.b + 20), 255) if active else bg
    rl.draw_rectangle_rounded(rect, 0.18, 10, color)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.18, 10, max(1, int(3 * self._ui_scale)), rl.Color(255, 170, 170, 150))
    text_size = measure_text_cached(self._font, label, font_size)
    pos = rl.Vector2(rect.x + (rect.width - text_size.x) / 2, rect.y + (rect.height - text_size.y) / 2)
    rl.draw_text_ex(self._font, label, pos, font_size, 0, rl.Color(255, 225, 220, 255))

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
      msg = "TAP RESTART FOR ANOTHER RUN"
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
    global _AUDIO_READY
    if self._audio_loaded:
      return

    _ensure_audio_files()
    if not _AUDIO_READY:
      rl.init_audio_device()
      _AUDIO_READY = True

    self._music = rl.load_music_stream(os.path.join(AUDIO_DIR, "start_music.wav"))
    self._success_sound = rl.load_sound(os.path.join(AUDIO_DIR, "success.wav"))
    self._death_sound = rl.load_sound(os.path.join(AUDIO_DIR, "death.wav"))
    rl.set_music_volume(self._music, 0.55)
    rl.set_sound_volume(self._success_sound, 0.70)
    rl.set_sound_volume(self._death_sound, 0.75)
    self._audio_loaded = True

  def _tick_audio(self):
    if self._audio_loaded and self._music is not None:
      rl.update_music_stream(self._music)

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
