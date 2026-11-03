from enum import StrEnum, auto

DOMAIN = "zeitgeber"


class Conf(StrEnum):
    MANAGED_ENTITIES = auto()
    DURATION = auto()
    MIN_COLOR_TEMP = auto()
    MAX_COLOR_TEMP = auto()
    MIN_BRIGHTNESS = auto()
    MAX_BRIGHTNESS = auto()
