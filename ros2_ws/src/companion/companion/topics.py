"""Topic names shared by every companion node: the pipeline's contract in one place.

    camera ──/camera/image/compressed──▶ brain ──/robot/say────▶ voice ──▶ speaker
    mic ─▶ hearing ──/speech/text──────▶ brain ──/robot/reply──▶ gateway (web UI)
    web UI ─▶ gateway ──/user/text─────▶ brain
                      ──/user/file─────▶ brain
    voice ──/robot/speaking──▶ hearing   (mutes the mic so the robot doesn't hear itself)

    face signals:  hearing ──/robot/listening─┐
                   brain ──/robot/thinking────┼─▶ gateway ──/robot/state──▶ face page (+ anyone)
                   voice ──/robot/speaking────┘
                   brain ──/robot/emotion─────▶ face page
                   voice ──/robot/mouth───────▶ face page (lip sync)
"""

IMAGE = "/camera/image/compressed"   # sensor_msgs/CompressedImage (JPEG)
SPEECH_TEXT = "/speech/text"         # std_msgs/String: what the user said, transcribed
USER_TEXT = "/user/text"             # std_msgs/String: typed message
USER_FILE = "/user/file"             # std_msgs/String: JSON {"path": str, "prompt": str?}
SAY = "/robot/say"                   # std_msgs/String: one sentence at a time, for TTS
REPLY = "/robot/reply"               # std_msgs/String: JSON {"role", "text", "source"}; full turns
SPEAKING = "/robot/speaking"         # std_msgs/Bool: true while audio is playing
LISTENING = "/robot/listening"       # std_msgs/Bool: true while the user is talking (VAD)
THINKING = "/robot/thinking"         # std_msgs/Bool: true while waiting on the model
STATE = "/robot/state"               # std_msgs/String: idle | listening | thinking | speaking
EMOTION = "/robot/emotion"           # std_msgs/String: one of EMOTIONS, set per reply
MOUTH = "/robot/mouth"               # std_msgs/String: JSON {"env": [0..1, ...], "dt": s}, per utterance

# The model tags each reply with one of these; the face has an expression for each.
EMOTIONS = ("neutral", "happy", "excited", "curious", "surprised", "sad", "confused", "love")
