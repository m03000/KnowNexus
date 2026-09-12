"""Isolated real model inference used by the desktop test button."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def main(args=None):
    from .manager import ModelManager
    kind, folder = args if args is not None else sys.argv[1:]
    if kind not in ('embedding', 'reranker'):
        raise ValueError('Unknown model kind')
    manager = ModelManager(SimpleNamespace(rag_embedding_model=folder,
                                          rag_reranker_model=folder,
                                          rag_model_cache_directory=Path(folder).parent))
    result = manager._probe_retrieval_model(kind)['test']
    print('KNOWNEXUS_MODEL_TEST=' + json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
