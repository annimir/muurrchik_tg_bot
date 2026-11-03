import unicodedata

from rapidfuzz import process, fuzz


class TagStorage:

    def __init__(self, similarity_threshold: int = 85):
        self.tags: dict[str, str] = {}
        self.similarity_threshold = similarity_threshold

    def normalize(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = text.casefold()
        return text.strip()

    @staticmethod
    def _collapse_repeated_letters(text: str) -> str:
        result = []
        for char in text:
            if not result or result[-1] != char:
                result.append(char)
        return ''.join(result)

    def load_from(self, existing_tags: list[str]):
        for tag in existing_tags:
            self.tags[self.normalize(tag)] = tag

    def load_aliases(self, alias_pairs: list[tuple[str, str]]):
        for alias, main_name in alias_pairs:
            self.tags[self.normalize(alias)] = main_name

    def replace(self, existing_tags: list[str], alias_pairs: list[tuple[str, str]]):
        updated = {}
        for tag in existing_tags:
            updated[self.normalize(tag)] = tag
        for alias, main_name in alias_pairs:
            updated[self.normalize(alias)] = main_name
        self.tags = updated

    def add_to_cache(self, tag: str):
        self.tags[self.normalize(tag)] = tag

    def add_alias_to_cache(self, alias: str, main_name: str):
        self.tags[self.normalize(alias)] = main_name

    def rename(self, old_name: str, new_name: str):
        old_normalized = self.normalize(old_name)
        for key, main_name in self.tags.items():
            if self.normalize(main_name) == old_normalized:
                self.tags[key] = new_name
        self.tags[self.normalize(new_name)] = new_name

    def is_taken(self, tag: str) -> bool:
        return self.normalize(tag) in self.tags

    def find(self, tag: str) -> dict:
        norm = self.normalize(tag)

        if norm in self.tags:
            return {"status": "found", "tag": self.tags[norm]}

        if not self.tags:
            return {"status": "created", "tag": tag}

        collapsed = self._collapse_repeated_letters(norm)
        collapsed_matches = {
            self.normalize(main_name): main_name
            for key, main_name in self.tags.items()
            if self._collapse_repeated_letters(key) == collapsed
        }
        if collapsed_matches:
            matched_name = min(
                collapsed_matches.values(),
                key=lambda name: (len(self.normalize(name)), self.normalize(name)),
            )
            return {"status": "suggest", "tag": matched_name, "score": 100.0}

        result = process.extractOne(norm, self.tags.keys(), scorer=fuzz.ratio)

        if result is None:
            return {"status": "created", "tag": tag}

        candidate, score, _ = result

        if score >= self.similarity_threshold:
            return {"status": "suggest", "tag": self.tags[candidate], "score": score}

        return {"status": "created", "tag": tag}


tag_storage = TagStorage()