#!/usr/bin/env python3
import os
import shutil
import threading
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog
from openpilot.system.loggerd.config import get_available_bytes, get_available_percent
from openpilot.system.loggerd.uploader import listdir_by_creation
from openpilot.system.loggerd.xattr_cache import getxattr

MIN_BYTES = 5 * 1024 * 1024 * 1024
MIN_PERCENT = 10

DELETE_LAST = ['boot', 'crash']

PRESERVE_ATTR_NAME = 'user.preserve'
PRESERVE_ATTR_VALUE = b'1'
PRESERVE_COUNT = 5


def has_preserve_xattr(d: str) -> bool:
  return getxattr(os.path.join(Paths.log_root(), d), PRESERVE_ATTR_NAME) == PRESERVE_ATTR_VALUE


def get_preserved_segments(dirs_by_creation: list[str]) -> list[str]:
  preserved = []
  for n, d in enumerate(filter(has_preserve_xattr, reversed(dirs_by_creation))):
    if n == PRESERVE_COUNT:
      break
    date_str, _, seg_str = d.rpartition("--")

    # ignore non-segment directories
    if not date_str:
      continue
    try:
      seg_num = int(seg_str)
    except ValueError:
      continue

    # preserve segment and two prior
    for _seg_num in range(max(0, seg_num - 2), seg_num + 1):
      preserved.append(f"{date_str}--{_seg_num}")

  return preserved


def deleter_thread(exit_event):
  while not exit_event.is_set():
    out_of_bytes_internal = get_available_bytes(path_type="internal", default=MIN_BYTES + 1) < MIN_BYTES
    out_of_percent_internal = get_available_percent(path_type="internal", default=MIN_PERCENT + 1) < MIN_PERCENT

    internal_path = Paths.log_root()
    external_path = Paths.log_root_external()

    # If the internal storage is out of space
    if out_of_percent_internal or out_of_bytes_internal:

      # Check if the external mount is alive.
      if os.path.ismount('/data/media/1') and os.path.exists(external_path):
        out_of_bytes_external = get_available_bytes(path_type="external", default=MIN_BYTES + 1) < MIN_BYTES
        out_of_percent_external = get_available_percent(path_type="external", default=MIN_PERCENT + 1) < MIN_PERCENT

        # If the external storage is out of space, delete from it.
        if out_of_bytes_external or out_of_percent_external:
          dirs = listdir_by_creation(external_path)

          for delete_dir in dirs:
            delete_path = os.path.join(external_path, delete_dir)

            if any(name.endswith(".lock") for name in os.listdir(delete_path)):
              continue

            try:
              cloudlog.info(f"deleting {delete_path}")
              if os.path.isfile(delete_path):
                os.remove(delete_path)
              else:
                shutil.rmtree(delete_path)
              break
            except OSError:
              cloudlog.exception(f"issue deleting {delete_path}")
          exit_event.wait(.1)

        # Move data from internal to external.
        dirs = listdir_by_creation(internal_path)
        preserved_dirs = get_preserved_segments(dirs)

        for delete_dir in sorted(dirs, key=lambda d: (d in DELETE_LAST, d in preserved_dirs)):
          move_from = os.path.join(internal_path, delete_dir)
          move_to = os.path.join(external_path, delete_dir)

          if any(name.endswith(".lock") for name in os.listdir(move_from)):
            continue
            
          try:
            cloudlog.info(f"moving {move_from} to {move_to}")
            shutil.move(move_from, move_to)
            break
          except Exception as e:
            cloudlog.exception(f"issue moving {move_from} to {move_to}: {str(e)}")
        exit_event.wait(.1)

      # If external storage is not mounted, delete from internal storage.
      else:
        dirs = listdir_by_creation(internal_path)
        preserved_dirs = get_preserved_segments(dirs)

        for delete_dir in sorted(dirs, key=lambda d: (d in DELETE_LAST, d in preserved_dirs)):
          delete_path = os.path.join(internal_path, delete_dir)

          if any(name.endswith(".lock") for name in os.listdir(delete_path)):
            continue

          try:
            cloudlog.info(f"deleting {delete_path}")
            if os.path.isfile(delete_path):
              os.remove(delete_path)
            else:
              shutil.rmtree(delete_path)
            break
          except OSError:
            cloudlog.exception(f"issue deleting {delete_path}")
        exit_event.wait(.1)

    else:
      exit_event.wait(30)


def main():
  deleter_thread(threading.Event())


if __name__ == "__main__":
  main()
