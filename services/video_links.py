import re

VIDEO_LINK_PATTERN = re.compile(
    r'https?://(?:[\w-]+\.)?(?:youtube\.com|youtu\.be|instagram\.com|instagr\.am|tiktok\.com)/\S+',
    re.IGNORECASE,
)
HASHTAG_PATTERN = re.compile(r'(?<![\w#])#([\w-]+)')


def extract_video_tags(text: str) -> list[str]:
    if not VIDEO_LINK_PATTERN.search(text):
        return []
    return HASHTAG_PATTERN.findall(text)
