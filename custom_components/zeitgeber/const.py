from enum import StrEnum, auto

from voluptuous import ScalarInvalid, Schema

DOMAIN = "zeitgeber"


class Conf(StrEnum):
    MANAGED_ENTITIES = auto()
    DURATION = auto()
    MIN_COLOR_TEMP = auto()
    MAX_COLOR_TEMP = auto()
    MIN_BRIGHTNESS = auto()
    MAX_BRIGHTNESS = auto()

    def __voluptuous_compile__(self, schema: Schema):
        def validate_value(path, data):
            if data != self:
                raise ScalarInvalid("not a valid value", path)
            return data

        return validate_value
