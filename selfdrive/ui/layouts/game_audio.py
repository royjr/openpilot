_AUDIO_READY = False


def ensure_audio_device(rl_module):
  global _AUDIO_READY
  if not _AUDIO_READY:
    rl_module.init_audio_device()
    _AUDIO_READY = True
