MAX_NAME_LENGTH = 100
MAX_TEXT_LENGTH = 600


def name_is_too_long(value: str) -> bool:
    return len(value) > MAX_NAME_LENGTH


def text_is_too_long(value: str) -> bool:
    return len(value) > MAX_TEXT_LENGTH
