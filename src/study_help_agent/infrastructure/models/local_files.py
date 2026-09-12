"""Resolve portable model folders without requiring unrelated Hub repository files."""
import json
from pathlib import Path


def _complete(folder: Path) -> bool:
    def present(name: str) -> bool:
        file = folder / name
        return file.is_file() and file.stat().st_size > 0
    if not present('config.json'):
        return False
    if not any(present(name) for name in ('tokenizer.json', 'vocab.txt', 'sentencepiece.bpe.model', 'spiece.model')):
        return False
    weights = any(present(name) for name in ('model.safetensors', 'pytorch_model.bin'))
    if not weights:
        for index in ('model.safetensors.index.json', 'pytorch_model.bin.index.json'):
            if present(index):
                shards = json.loads((folder / index).read_text(encoding='utf-8')).get('weight_map', {})
                weights = bool(shards) and all(present(name) for name in set(shards.values()))
                if weights:
                    break
    if not weights:
        return False
    if present('modules.json'):
        for module in json.loads((folder / 'modules.json').read_text(encoding='utf-8')):
            relative = module.get('path', '')
            if relative and module.get('type', '').endswith('.Pooling') and not present(relative + '/config.json'):
                return False
    return True


def resolve_local_model(model_id: str, cache_directory: str | Path) -> Path:
    cache = Path(cache_directory)
    candidates = [Path(model_id), cache / model_id.split('/')[-1], cache / model_id]
    repository = cache / ('models--' + model_id.replace('/', '--'))
    ref = repository / 'refs' / 'main'
    if ref.is_file():
        candidates.append(repository / 'snapshots' / ref.read_text(encoding='utf-8').strip())
    snapshots = repository / 'snapshots'
    if snapshots.is_dir():
        candidates.extend(sorted(snapshots.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True))
    for folder in candidates:
        try:
            if folder.is_dir() and _complete(folder):
                return folder.resolve()
        except (OSError, ValueError, TypeError, KeyError):
            continue
    raise FileNotFoundError(f'模型 {model_id} 的配置、分词器或权重不完整。请下载或复制完整模型到 {cache}')
