import unicodedata

from rapidfuzz import process, fuzz


class TagStorage:

    def __init__(self, similarity_threshold: int = 90):
        self.tags: dict[str, str] = {}
        self.similarity_threshold = similarity_threshold

    def normalize(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = text.casefold()
        return text.strip()

    def load_from(self, existing_tags: list[str]):
        for tag in existing_tags:
            self.tags[self.normalize(tag)] = tag

    def load_aliases(self, alias_pairs: list[tuple[str, str]]):
        for alias, main_name in alias_pairs:
            self.tags[self.normalize(alias)] = main_name

    def add_to_cache(self, tag: str):
        self.tags[self.normalize(tag)] = tag

    def add_alias_to_cache(self, alias: str, main_name: str):
        self.tags[self.normalize(alias)] = main_name

    def is_taken(self, tag: str) -> bool:
        return self.normalize(tag) in self.tags

    def find(self, tag: str) -> dict:
        norm = self.normalize(tag)

        if norm in self.tags:
            return {"status": "found", "tag": self.tags[norm]}

        if not self.tags:
            return {"status": "created", "tag": tag}

        result = process.extractOne(norm, self.tags.keys(), scorer=fuzz.ratio)

        if result is None:
            return {"status": "created", "tag": tag}

        candidate, score, _ = result

        if score >= self.similarity_threshold:
            return {"status": "suggest", "tag": self.tags[candidate], "score": score}

        return {"status": "created", "tag": tag}


tag_storage = TagStorage()