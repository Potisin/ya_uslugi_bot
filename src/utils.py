import json


def get_keywords() -> list[str]:
    with open('data/keywords.json', encoding='utf-8') as file:
        keywords = json.load(file)
        return keywords


def set_keywords(keywords: list[str]) -> None:
    with open('data/keywords.json', 'w', encoding='utf-8') as file:
        json.dump(keywords, file, indent=4, ensure_ascii=False)
