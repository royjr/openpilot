#!/usr/bin/env python3
import argparse
import math
import os
import sys
import tempfile
from dataclasses import dataclass

import cv2
import numpy as np
import pyray as rl

import cereal.messaging as messaging
from opendbc.can.parser import CANParser
from openpilot.common.basedir import BASEDIR
from openpilot.common.transformations.camera import DEVICE_CAMERAS
from openpilot.tools.replay.lib.ui_helpers import (
  UP,
  BLACK,
  GREEN,
  YELLOW,
  Calibration,
  get_blank_lid_overlay,
  init_plots,
  plot_lead,
  plot_model,
  to_topdown_pt,
)
from openpilot.selfdrive.controls.radard import RADAR_TO_CAMERA
from msgq.visionipc import VisionIpcClient, VisionStreamType

os.environ['BASEDIR'] = BASEDIR

ANGLE_SCALE = 5.0
RADAR_500_51F_ADDR = 0x500
RADAR_500_51F_COUNT = 32
RADAR_602_611_ADDR = 0x602
RADAR_602_611_COUNT = 16
RADAR_210_21F_ADDR = 0x210
RADAR_210_21F_COUNT = 16
RADAR_3A5_3C4_ADDR = 0x3A5
RADAR_3A5_3C4_COUNT = 32
RADAR_3A5_3C4_TRACK_LEN = 24
RADAR_TRACK_TIMEOUT_FRAMES = 10
RADAR_FORMAT_SWITCH_MISS_FRAMES = 30
RADAR_TRACK_RADIUS = 4
CAMERA_RADAR_Y_OFFSET = 25
RADAR_500_51F_DBC_TEMPLATE = """
BO_ {addr_dec} RADAR_TRACK_{addr_hex}: 8 RADAR
 SG_ UNKNOWN_1 : 7|8@0- (1,0) [-128|127] "" XXX
 SG_ AZIMUTH : 12|10@0- (0.2,0) [-102.4|102.2] "" XXX
 SG_ STATE : 15|3@0+ (1,0) [0|7] "" XXX
 SG_ LONG_DIST : 18|11@0+ (0.1,0) [0|204.7] "" XXX
 SG_ REL_ACCEL : 33|10@0- (0.02,0) [-10.24|10.22] "" XXX
 SG_ ZEROS : 37|4@0+ (1,0) [0|255] "" XXX
 SG_ COUNTER : 38|1@0+ (1,0) [0|1] "" XXX
 SG_ STATE_3 : 39|1@0+ (1,0) [0|1] "" XXX
 SG_ REL_SPEED : 53|14@0- (0.01,0) [-81.92|81.92] "" XXX
 SG_ STATE_2 : 55|2@0+ (1,0) [0|3] "" XXX
"""
RADAR_3A5_3C4_DBC_TEMPLATE = """
BO_ {addr_dec} RADAR_TRACK_{addr_hex}: 24 RADAR
 SG_ CHECKSUM : 0|16@1+ (1,0) [0|65535] "" XXX
 SG_ COUNTER : 16|8@1+ (1,0) [0|255] "" XXX
 SG_ NEW_SIGNAL_1 : 25|2@0+ (1,0) [0|3] "" XXX
 SG_ NEW_SIGNAL_3 : 28|2@0+ (1,0) [0|3] "" XXX
 SG_ COUNTER_3 : 31|2@0+ (1,0) [0|3] "" XXX
 SG_ NEW_SIGNAL_2 : 38|7@0- (1,0) [0|127] "" XXX
 SG_ COUNTER_256 : 47|8@0+ (1,0) [0|255] "" XXX
 SG_ NEW_SIGNAL_6 : 51|4@0+ (1,0) [0|15] "" XXX
 SG_ STATE : 54|3@0+ (1,0) [0|7] "" XXX
 SG_ NEW_SIGNAL_8 : 62|7@0- (1,0) [0|127] "" XXX
 SG_ LONG_DIST : 63|12@1+ (0.05,0) [0|8191] "m" XXX
 SG_ LAT_DIST : 76|12@1- (0.05,0) [0|127] "" XXX
 SG_ REL_SPEED : 88|14@1- (0.01,0) [0|16383] "" XXX
 SG_ NEW_SIGNAL_4 : 103|2@0+ (1,0) [0|3] "" XXX
 SG_ LAT_DIST_ACCEL : 104|13@1- (1,0) [0|8191] "" XXX
 SG_ REL_ACCEL : 118|10@1- (0.02,0) [0|1023] "" XXX
 SG_ NEW_SIGNAL_5 : 133|4@0+ (1,0) [0|15] "" XXX
"""


@dataclass
class RadarTrackPoint:
  trackId: int
  measured: bool = True
  dRel: float = 0.0
  yRel: float = 0.0
  vRel: float = 0.0
  aRel: float = 0.0
  yvRel: float = float("nan")


@dataclass(frozen=True)
class RadarFormat:
  name: str
  start_addr: int
  msg_count: int
  dbc_template: str
  track_prefixes: tuple[str, ...]
  has_state: bool = True

  @property
  def end_addr(self) -> int:
    return self.start_addr + self.msg_count - 1


RADAR_210_21F_DBC_TEMPLATE = """
BO_ {addr_dec} RADAR_TRACK_{addr_hex}: 32 RADAR
 SG_ CHECKSUM : 0|16@1+ (1,0) [0|65535] "" XXX
 SG_ COUNTER : 16|8@1+ (1,0) [0|255] "" XXX
 SG_ 1_COUNTER_255 : 47|8@0+ (1,0) [0|255] "" XXX
 SG_ 1_STATE_ALT : 51|4@0+ (1,0) [0|15] "" XXX
 SG_ 1_STATE : 55|4@0+ (1,0) [0|15] "" XXX
 SG_ 1_NEW_SIGNAL_3 : 63|8@0- (1,0) [0|255] "" XXX
 SG_ 1_LONG_DIST : 64|12@1+ (0.05,0) [0|4095] "" XXX
 SG_ 1_LAT_DIST : 76|12@1- (0.05,0) [0|4095] "" XXX
 SG_ 1_REL_SPEED : 88|14@1- (0.01,0) [0|16383] "" XXX
 SG_ 1_NEW_SIGNAL_1 : 102|2@1+ (1,0) [0|3] "" XXX
 SG_ 1_LAT_ACCEL : 104|13@1- (1,0) [0|8191] "" XXX
 SG_ 1_REL_ACCEL : 118|10@1- (1,0) [0|1023] "" XXX
 SG_ 2_COUNTER_255 : 175|8@0+ (1,0) [0|255] "" XXX
 SG_ 2_STATE_ALT : 179|4@0+ (1,0) [0|15] "" XXX
 SG_ 2_STATE : 183|4@0+ (1,0) [0|15] "" XXX
 SG_ 2_NEW_SIGNAL_3 : 191|8@0- (1,0) [0|255] "" XXX
 SG_ 2_LONG_DIST : 192|12@1+ (0.05,0) [0|4095] "" XXX
 SG_ 2_LAT_DIST : 204|12@1- (0.05,0) [0|4095] "" XXX
 SG_ 2_REL_SPEED : 216|14@1- (0.01,0) [0|65535] "" XXX
 SG_ 2_NEW_SIGNAL_1 : 230|2@1+ (1,0) [0|3] "" XXX
 SG_ 2_LAT_ACCEL : 232|13@1- (1,0) [0|8191] "" XXX
 SG_ 2_REL_ACCEL : 246|10@1- (1,0) [0|1023] "" XXX
"""

RADAR_602_611_DBC_TEMPLATE = """
BO_ {addr_dec} RADAR_TRACK_{addr_hex}: 8 RADAR
 SG_ 1_DISTANCE : 0|10@1+ (0.25,0) [0|255.75] "" XXX
 SG_ 1_LATERAL : 10|11@1+ (0.03,-30.705) [-30.705|30.705] "" XXX
 SG_ 1_SPEED : 21|10@1+ (0.25,-128) [-128|127.75] "" XXX
 SG_ 2_DISTANCE : 31|10@1+ (0.25,0) [0|255.75] "" XXX
 SG_ 2_LATERAL : 41|11@1+ (0.03,-30.705) [-30.705|30.705] "" XXX
 SG_ 2_SPEED : 52|10@1+ (0.25,-128) [-128|127.75] "" XXX
 SG_ COUNTER : 62|2@1+ (1,0) [0|3] "" XXX
"""

RADAR_FORMATS = (
  RadarFormat("RADAR_500_51F", RADAR_500_51F_ADDR, RADAR_500_51F_COUNT, RADAR_500_51F_DBC_TEMPLATE, ("",)),
  RadarFormat("RADAR_3A5_3C4", RADAR_3A5_3C4_ADDR, RADAR_3A5_3C4_COUNT, RADAR_3A5_3C4_DBC_TEMPLATE, ("",)),
  RadarFormat("RADAR_210_21F", RADAR_210_21F_ADDR, RADAR_210_21F_COUNT, RADAR_210_21F_DBC_TEMPLATE, ("1_", "2_")),
  RadarFormat("RADAR_602_611", RADAR_602_611_ADDR, RADAR_602_611_COUNT, RADAR_602_611_DBC_TEMPLATE, ("1_", "2_"), has_state=False),
)


def get_radar_format(address: int) -> RadarFormat | None:
  for radar_format in RADAR_FORMATS:
    if radar_format.start_addr <= address <= radar_format.end_addr:
      return radar_format
  return None


def is_exclusive_full_range_match(radar_format: RadarFormat, seen_addresses: dict[str, set[int]]) -> bool:
  expected_addresses = set(range(radar_format.start_addr, radar_format.end_addr + 1))
  if seen_addresses[radar_format.name] != expected_addresses:
    return False

  for other_format in RADAR_FORMATS:
    if other_format.name == radar_format.name:
      continue

    other_expected_addresses = set(range(other_format.start_addr, other_format.end_addr + 1))
    if seen_addresses[other_format.name] == other_expected_addresses:
      return False

  return True


def get_radar_dbc_path(radar_format: RadarFormat) -> str:
  dbc_path = os.path.join(tempfile.gettempdir(), f"{radar_format.name.lower()}_radar_ui.dbc")
  dbc_content = "\n".join(
    radar_format.dbc_template.format(addr_dec=addr, addr_hex=f"{addr:x}")
    for addr in range(radar_format.start_addr, radar_format.end_addr + 1)
  )
  if not os.path.exists(dbc_path) or open(dbc_path).read() != dbc_content:
    with open(dbc_path, "w") as f:
      f.write(dbc_content)
  return dbc_path


def get_radar_can_parser(radar_format: RadarFormat, bus: int) -> CANParser:
  messages = [(f"RADAR_TRACK_{addr:x}", 50) for addr in range(radar_format.start_addr, radar_format.end_addr + 1)]
  return CANParser(get_radar_dbc_path(radar_format), messages, bus)


def get_track_storage_key(radar_format: RadarFormat, bus: int, addr: int, track_prefix: str) -> tuple[str, int, int]:
  if radar_format.name in ("RADAR_500_51F", "RADAR_3A5_3C4"):
    return (radar_format.name, bus, addr)

  track_index = int(track_prefix[0]) - 1
  return (radar_format.name, bus, addr * 2 + track_index)


def draw_radar_points(tracks, lid_overlay):
  for track in tracks:
    px, py = to_topdown_pt(track.dRel, -track.yRel)
    if px != -1:
      cv2.circle(lid_overlay, (py, px), RADAR_TRACK_RADIUS, 255, thickness=-1, lineType=cv2.LINE_AA)


def draw_radar_points_camera(tracks, img, calibration):
  if calibration is None:
    return

  for track in tracks:
    if track.dRel <= 0.0:
      continue

    # Match the road-space projection convention used by other UI overlays.
    pt = calibration.car_space_to_bb(
      np.asarray([track.dRel - RADAR_TO_CAMERA]),
      np.asarray([-track.yRel]),
      np.asarray([1.0]),
    )
    x, y = np.round(pt[0]).astype(int)
    y += CAMERA_RADAR_Y_OFFSET
    if 0 <= x < img.shape[1] and 0 <= y < img.shape[0]:
      cv2.circle(img, (x, y), RADAR_TRACK_RADIUS, (255, 255, 255), thickness=-1, lineType=cv2.LINE_AA)


def ui_thread(addr):
  cv2.setNumThreads(1)

  # Get monitor info before creating window
  rl.set_config_flags(rl.ConfigFlags.FLAG_MSAA_4X_HINT)
  rl.init_window(1, 1, "")
  max_height = rl.get_monitor_height(0)
  rl.close_window()

  hor_mode = os.getenv("HORIZONTAL") is not None
  hor_mode = True if max_height < 960 + 300 else hor_mode

  if hor_mode:
    size = (640 + 384 + 640, 960)
    write_x = 5
    write_y = 680
  else:
    size = (640 + 384, 960 + 300)
    write_x = 645
    write_y = 970

  rl.set_trace_log_level(rl.TraceLogLevel.LOG_ERROR)
  rl.set_config_flags(rl.ConfigFlags.FLAG_MSAA_4X_HINT)
  rl.init_window(size[0], size[1], "openpilot debug UI")
  rl.set_target_fps(60)

  # Load font
  font_path = os.path.join(BASEDIR, "selfdrive/assets/fonts/JetBrainsMono-Medium.ttf")
  font = rl.load_font_ex(font_path, 32, None, 0)

  # Create textures for camera and top-down view
  camera_image = rl.gen_image_color(640, 480, rl.BLACK)
  camera_texture = rl.load_texture_from_image(camera_image)
  rl.unload_image(camera_image)

  # lid_overlay array is (lidar_x, lidar_y) = (384, 960)
  # pygame treats first axis as width, so texture is 384 wide x 960 tall
  # For raylib, we need to transpose to get (height, width) = (960, 384) for the RGBA array
  top_down_image = rl.gen_image_color(UP.lidar_x, UP.lidar_y, rl.BLACK)
  top_down_texture = rl.load_texture_from_image(top_down_image)
  rl.unload_image(top_down_image)

  sm = messaging.SubMaster(
    [
      'carState',
      'longitudinalPlan',
      'carControl',
      'radarState',
      'liveCalibration',
      'controlsState',
      'selfdriveState',
      'liveTracks',
      'modelV2',
      'liveParameters',
      'roadCameraState',
      'can',
    ],
    addr=addr,
  )

  img = np.zeros((480, 640, 3), dtype='uint8')
  imgff = None
  num_px = 0
  calibration = None
  can_range_msg_count = 0
  active_radar_format_name = None
  active_radar_format_miss_count = 0
  radar_format_total_counts = {radar_format.name: 0 for radar_format in RADAR_FORMATS}
  radar_format_seen_addresses = {radar_format.name: set() for radar_format in RADAR_FORMATS}
  radar_track_ids: dict[tuple[str, int, int], int] = {}
  next_radar_track_id = 0
  radar_tracks: dict[tuple[str, int, int], RadarTrackPoint] = {}
  radar_track_last_seen: dict[tuple[str, int, int], int] = {}
  radar_parsers: dict[str, dict[int, CANParser]] = {}

  lid_overlay_blank = get_blank_lid_overlay(UP)

  # plots
  name_to_arr_idx = {
    "gas": 0,
    "computer_gas": 1,
    "user_brake": 2,
    "computer_brake": 3,
    "v_ego": 4,
    "v_pid": 5,
    "angle_steers_des": 6,
    "angle_steers": 7,
    "angle_steers_k": 8,
    "steer_torque": 9,
    "v_override": 10,
    "v_cruise": 11,
    "a_ego": 12,
    "a_target": 13,
  }

  plot_arr = np.zeros((100, len(name_to_arr_idx.values())))

  plot_xlims = [(0, plot_arr.shape[0]), (0, plot_arr.shape[0]), (0, plot_arr.shape[0]), (0, plot_arr.shape[0])]
  plot_ylims = [(-0.1, 1.1), (-ANGLE_SCALE, ANGLE_SCALE), (0.0, 75.0), (-3.0, 2.0)]
  plot_names = [
    ["gas", "computer_gas", "user_brake", "computer_brake"],
    ["angle_steers", "angle_steers_des", "angle_steers_k", "steer_torque"],
    ["v_ego", "v_override", "v_pid", "v_cruise"],
    ["a_ego", "a_target"],
  ]
  plot_colors = [["b", "b", "g", "r", "y"], ["b", "g", "y", "r"], ["b", "g", "r", "y"], ["b", "r"]]
  plot_styles = [["-", "-", "-", "-", "-"], ["-", "-", "-", "-"], ["-", "-", "-", "-"], ["-", "-"]]

  draw_plots = init_plots(plot_arr, name_to_arr_idx, plot_xlims, plot_ylims, plot_names, plot_colors, plot_styles)

  # Palette for converting lid_overlay grayscale indices to RGBA colors
  palette = np.zeros((256, 4), dtype=np.uint8)
  palette[:, 3] = 255  # alpha
  palette[1] = [255, 0, 0, 255]  # RED
  palette[2] = [0, 255, 0, 255]  # GREEN
  palette[3] = [0, 0, 255, 255]  # BLUE
  palette[4] = [255, 255, 0, 255]  # YELLOW
  palette[110] = [110, 110, 110, 255]  # car_color (gray)
  palette[255] = [255, 255, 255, 255]  # WHITE

  vipc_client = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_ROAD, True)
  while not rl.window_should_close():
    # ***** frame *****
    if not vipc_client.is_connected():
      vipc_client.connect(False)

    rl.begin_drawing()
    rl.clear_background(rl.Color(64, 64, 64, 255))

    yuv_img_raw = vipc_client.recv()
    if yuv_img_raw is None or not yuv_img_raw.data.any():
      rl.draw_text_ex(font, "waiting for frames", rl.Vector2(200, 200), 30, 0, rl.WHITE)
      rl.end_drawing()
      continue

    lid_overlay = lid_overlay_blank.copy()
    top_down = top_down_texture, lid_overlay

    sm.update(0)

    camera = DEVICE_CAMERAS[("tici", str(sm['roadCameraState'].sensor))]

    # Use received buffer dimensions (full HEVC can have stride != buffer_len/rows due to VENUS padding)
    h, w, stride = yuv_img_raw.height, yuv_img_raw.width, yuv_img_raw.stride
    nv12_size = h * 3 // 2 * stride
    imgff = np.frombuffer(yuv_img_raw.data, dtype=np.uint8, count=nv12_size).reshape((h * 3 // 2, stride))
    num_px = w * h
    rgb = cv2.cvtColor(imgff[: h * 3 // 2, : w], cv2.COLOR_YUV2RGB_NV12)

    qcam = "QCAM" in os.environ
    bb_scale = 0.8
    calib_scale = camera.fcam.width / 640.0
    zoom_matrix = np.asarray([[bb_scale, 0.0, 0.0], [0.0, bb_scale, 0.0], [0.0, 0.0, 1.0]])
    cv2.warpAffine(rgb, zoom_matrix[:2], (img.shape[1], img.shape[0]), dst=img, flags=cv2.WARP_INVERSE_MAP)

    intrinsic_matrix = camera.fcam.intrinsics

    w = sm['controlsState'].lateralControlState.which()
    if w == 'lqrStateDEPRECATED':
      angle_steers_k = sm['controlsState'].lateralControlState.lqrStateDEPRECATED.steeringAngleDeg
    elif w == 'indiState':
      angle_steers_k = sm['controlsState'].lateralControlState.indiState.steeringAngleDeg
    else:
      angle_steers_k = np.inf

    plot_arr[:-1] = plot_arr[1:]
    plot_arr[-1, name_to_arr_idx['angle_steers']] = sm['carState'].steeringAngleDeg
    plot_arr[-1, name_to_arr_idx['angle_steers_des']] = sm['carControl'].actuators.steeringAngleDeg
    plot_arr[-1, name_to_arr_idx['angle_steers_k']] = angle_steers_k
    plot_arr[-1, name_to_arr_idx['gas']] = sm['carState'].gasDEPRECATED
    # TODO gas is deprecated
    plot_arr[-1, name_to_arr_idx['computer_gas']] = np.clip(sm['carControl'].actuators.accel / 4.0, 0.0, 1.0)
    plot_arr[-1, name_to_arr_idx['user_brake']] = sm['carState'].brake
    plot_arr[-1, name_to_arr_idx['steer_torque']] = sm['carControl'].actuators.torque * ANGLE_SCALE
    # TODO brake is deprecated
    plot_arr[-1, name_to_arr_idx['computer_brake']] = np.clip(-sm['carControl'].actuators.accel / 4.0, 0.0, 1.0)
    plot_arr[-1, name_to_arr_idx['v_ego']] = sm['carState'].vEgo
    plot_arr[-1, name_to_arr_idx['v_cruise']] = sm['carState'].cruiseState.speed
    plot_arr[-1, name_to_arr_idx['a_ego']] = sm['carState'].aEgo

    if len(sm['longitudinalPlan'].accels):
      plot_arr[-1, name_to_arr_idx['a_target']] = sm['longitudinalPlan'].accels[0]

    if sm.recv_frame['modelV2']:
      plot_model(sm['modelV2'], img, calibration, top_down)

    if sm.recv_frame['radarState']:
      plot_lead(sm['radarState'], top_down)

    if sm.updated['liveCalibration'] and num_px:
      rpyCalib = np.asarray(sm['liveCalibration'].rpyCalib)
      calibration = Calibration(num_px, rpyCalib, intrinsic_matrix, calib_scale)

    if sm.updated['can']:
      can_strings = [(sm.logMonoTime['can'], [(msg.address, msg.dat, msg.src) for msg in sm['can']])]
      detected_format_counts = {radar_format.name: 0 for radar_format in RADAR_FORMATS}

      for msg in sm['can']:
        radar_format = get_radar_format(msg.address)
        if radar_format is not None:
          can_range_msg_count += 1
          detected_format_counts[radar_format.name] += 1
          radar_format_total_counts[radar_format.name] += 1
          radar_format_seen_addresses[radar_format.name].add(msg.address)
          if radar_format.name not in radar_parsers:
            radar_parsers[radar_format.name] = {}
          if msg.src not in radar_parsers[radar_format.name]:
            radar_parsers[radar_format.name][msg.src] = get_radar_can_parser(radar_format, msg.src)

      matching_formats = [
        radar_format.name
        for radar_format in RADAR_FORMATS
        if is_exclusive_full_range_match(radar_format, radar_format_seen_addresses)
      ]
      if len(matching_formats) == 1:
        if active_radar_format_name == matching_formats[0]:
          active_radar_format_miss_count = 0
        elif active_radar_format_name is None:
          active_radar_format_name = matching_formats[0]
          active_radar_format_miss_count = 0
        else:
          active_radar_format_miss_count += 1
          if active_radar_format_miss_count >= RADAR_FORMAT_SWITCH_MISS_FRAMES:
            active_radar_format_name = matching_formats[0]
            active_radar_format_miss_count = 0
      elif len(matching_formats) == 0 and active_radar_format_name is not None:
        active_radar_format_miss_count += 1
        if active_radar_format_miss_count >= RADAR_FORMAT_SWITCH_MISS_FRAMES:
          active_radar_format_name = None
          active_radar_format_miss_count = 0

      active_radar_format = next((fmt for fmt in RADAR_FORMATS if fmt.name == active_radar_format_name), None)
      if active_radar_format is not None:
        for bus, parser in radar_parsers.get(active_radar_format.name, {}).items():
          updated_addrs = parser.update(can_strings)
          relevant_updated_addrs = {
            track_addr for track_addr in updated_addrs
            if active_radar_format.start_addr <= track_addr <= active_radar_format.end_addr
          }
          if not relevant_updated_addrs:
            continue

          for track_addr in relevant_updated_addrs:
            msg_name = f"RADAR_TRACK_{track_addr:x}"
            track_msg = parser.vl[msg_name]
            for track_prefix in active_radar_format.track_prefixes:
              track_key = get_track_storage_key(active_radar_format, bus, track_addr, track_prefix)
              if active_radar_format.name == "RADAR_602_611":
                ts_nanos = parser.ts_nanos[msg_name][f"{track_prefix}DISTANCE"]
              elif active_radar_format.name == "RADAR_210_21F":
                ts_nanos = parser.ts_nanos[msg_name][f"{track_prefix}LONG_DIST"]
              else:
                ts_nanos = parser.ts_nanos[msg_name]["LONG_DIST"]
              if ts_nanos == 0:
                continue

              if active_radar_format.name == "RADAR_602_611":
                d_rel = track_msg[f"{track_prefix}DISTANCE"]
                # if d_rel == 255.75:
                #   radar_tracks.pop(track_key, None)
                #   radar_track_last_seen.pop(track_key, None)
                #   continue
                y_rel = track_msg[f"{track_prefix}LATERAL"]
                v_rel = track_msg[f"{track_prefix}SPEED"]
                a_rel = float("nan")
              elif active_radar_format.name == "RADAR_210_21F":
                # if track_msg[f"{track_prefix}STATE"] not in (3, 4):
                #   radar_tracks.pop(track_key, None)
                #   radar_track_last_seen.pop(track_key, None)
                #   continue
                d_rel = track_msg[f"{track_prefix}LONG_DIST"]
                y_rel = track_msg[f"{track_prefix}LAT_DIST"]
                v_rel = track_msg[f"{track_prefix}REL_SPEED"]
                a_rel = float("nan")
              elif active_radar_format.name == "RADAR_500_51F":
                # if track_msg["STATE"] not in (3, 4):
                #   radar_tracks.pop(track_key, None)
                #   radar_track_last_seen.pop(track_key, None)
                #   continue
                azimuth = math.radians(track_msg["AZIMUTH"])
                d_rel = math.cos(azimuth) * track_msg["LONG_DIST"]
                y_rel = 0.5 * -math.sin(azimuth) * track_msg["LONG_DIST"]
                v_rel = track_msg["REL_SPEED"]
                a_rel = track_msg["REL_ACCEL"]
              else:
                # if track_msg["STATE"] not in (3, 4):
                #   radar_tracks.pop(track_key, None)
                #   radar_track_last_seen.pop(track_key, None)
                #   continue
                d_rel = track_msg["LONG_DIST"]
                y_rel = track_msg["LAT_DIST"]
                v_rel = track_msg["REL_SPEED"]
                a_rel = track_msg["REL_ACCEL"]

              if track_key not in radar_track_ids:
                radar_track_ids[track_key] = next_radar_track_id
                next_radar_track_id += 1

              radar_tracks[track_key] = RadarTrackPoint(
                trackId=radar_track_ids[track_key],
                dRel=d_rel,
                yRel=y_rel,
                vRel=v_rel,
                aRel=a_rel,
              )
              radar_track_last_seen[track_key] = sm.frame

      stale_tracks = [
        track_key for track_key, last_seen in radar_track_last_seen.items()
        if (sm.frame - last_seen) > RADAR_TRACK_TIMEOUT_FRAMES
      ]
      for track_key in stale_tracks:
        radar_track_last_seen.pop(track_key, None)
        radar_tracks.pop(track_key, None)

    active_radar_tracks = [
      track for track_key, track in radar_tracks.items()
      if active_radar_format_name is not None and track_key[0] == active_radar_format_name
    ]
    if len(active_radar_tracks) == 0:
      active_radar_tracks = sm['liveTracks'].points

    # draw decoded radar tracks when present, otherwise fall back to liveTracks
    draw_radar_points(active_radar_tracks, top_down[1])
    draw_radar_points_camera(active_radar_tracks, img, calibration)

    # *** blits ***
    # Update camera texture from numpy array
    img_rgba = cv2.cvtColor(img, cv2.COLOR_RGB2RGBA)
    rl.update_texture(camera_texture, rl.ffi.cast("void *", img_rgba.ctypes.data))
    rl.draw_texture(camera_texture, 0, 0, rl.WHITE)  # noqa: TID251

    # display alerts
    rl.draw_text_ex(font, sm['selfdriveState'].alertText1, rl.Vector2(180, 150), 30, 0, rl.RED)
    rl.draw_text_ex(font, sm['selfdriveState'].alertText2, rl.Vector2(180, 190), 20, 0, rl.RED)

    # draw plots (texture is reused internally)
    plot_texture = draw_plots(plot_arr)
    if hor_mode:
      rl.draw_texture(plot_texture, 640 + 384, 0, rl.WHITE)  # noqa: TID251
    else:
      rl.draw_texture(plot_texture, 0, 600, rl.WHITE)  # noqa: TID251

    # Convert lid_overlay to RGBA and update top_down texture
    # lid_overlay is (384, 960), need to transpose to (960, 384) for row-major RGBA buffer
    lid_rgba = palette[lid_overlay.T]
    rl.update_texture(top_down_texture, rl.ffi.cast("void *", np.ascontiguousarray(lid_rgba).ctypes.data))
    rl.draw_texture(top_down_texture, 640, 0, rl.WHITE)  # noqa: TID251

    SPACING = 25
    lines = [
      ("ENABLED", GREEN if sm['selfdriveState'].enabled else BLACK),
      ("SPEED: " + str(round(sm['carState'].vEgo, 1)) + " m/s", YELLOW),
      ("LONG CONTROL STATE: " + str(sm['controlsState'].longControlState), YELLOW),
      ("LONG MPC SOURCE: " + str(sm['longitudinalPlan'].longitudinalPlanSource), YELLOW),
      None,
      (f"RADAR FORMAT: {active_radar_format_name or 'NONE'}", YELLOW),
      (f"RADAR CAN MSGS: {can_range_msg_count}", YELLOW),
      (f"RADAR TRACKS: {len(active_radar_tracks)}", YELLOW),
      ("ANGLE OFFSET (AVG): " + str(round(sm['liveParameters'].angleOffsetAverageDeg, 2)) + " deg", YELLOW),
      ("ANGLE OFFSET (INSTANT): " + str(round(sm['liveParameters'].angleOffsetDeg, 2)) + " deg", YELLOW),
      ("STIFFNESS: " + str(round(sm['liveParameters'].stiffnessFactor * 100.0, 2)) + " %", YELLOW),
      ("STEER RATIO: " + str(round(sm['liveParameters'].steerRatio, 2)), YELLOW),
    ]

    for i, line in enumerate(lines):
      if line is not None:
        color = rl.Color(line[1][0], line[1][1], line[1][2], 255)
        rl.draw_text_ex(font, line[0], rl.Vector2(write_x, write_y + i * SPACING), 20, 0, color)

    rl.end_drawing()

  rl.unload_texture(camera_texture)
  rl.unload_texture(top_down_texture)
  rl.unload_font(font)
  rl.close_window()


def get_arg_parser():
  parser = argparse.ArgumentParser(description="Show replay data in a UI.", formatter_class=argparse.ArgumentDefaultsHelpFormatter)

  parser.add_argument("ip_address", nargs="?", default="127.0.0.1", help="The ip address on which to receive zmq messages.")

  parser.add_argument("--frame-address", default=None, help="The frame address (fully qualified ZMQ endpoint for frames) on which to receive zmq messages.")
  return parser


if __name__ == "__main__":
  args = get_arg_parser().parse_args(sys.argv[1:])

  if args.ip_address != "127.0.0.1":
    os.environ["ZMQ"] = "1"
    messaging.reset_context()

  ui_thread(args.ip_address)
