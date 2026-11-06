import re

MAX_NAME_LENGTH = 100
MAX_TEXT_LENGTH = 600
TAG_NAME_PATTERN = re.compile(r'^[\w-]+$')


def is_valid_tag_name(value: str) -> bool:
    return bool(TAG_NAME_PATTERN.fullmatch(value))


def name_is_too_long(value: str) -> bool:
    return len(value) > MAX_NAME_LENGTH


def text_is_too_long(value: str) -> bool:
    return len(value) > MAX_TEXT_LENGTH
