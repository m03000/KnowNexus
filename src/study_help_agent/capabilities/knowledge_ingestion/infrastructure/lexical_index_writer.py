"""为 SQLite FTS5 生成稳定的中英文关键词文本。"""

import re


class LexicalTextEncoder:
    """优先使用 jieba；未安装时用中文单字/双字词和英文单词安全降级。"""

    _groups = re.compile(r"[\u3400-\u9fff]+|[A-Za-z0-9_]+")

    def terms(self, text: str) -> tuple[str, ...]:
        """返回适合 FTS5 unicode61 tokenizer 的空格分隔词元。"""

        try:
            import jieba

            return tuple(term.strip() for term in jieba.lcut(text) if term.strip())
        except ModuleNotFoundError:
            terms: list[str] = []
            for group in self._groups.findall(text):
                if re.fullmatch(r"[\u3400-\u9fff]+", group):
                    terms.extend(group)
                    terms.extend(group[index : index + 2] for index in range(len(group) - 1))
                else:
                    terms.append(group.casefold())
            return tuple(dict.fromkeys(terms))

    def encode(self, text: str) -> str:
        """把词元转换成供 FTS5 写入的安全文本。"""

        return " ".join(self.terms(text))
