from enum import Enum


class ImagePolicy(str, Enum):
    DISABLED = "disabled"
    MINIMAL = "minimal"
    STANDARD = "standard"
