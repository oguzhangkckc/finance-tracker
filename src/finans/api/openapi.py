"""OpenAPI şeması; `make openapi` repodaki `frontend/src/api/openapi.json`'ı üretir (K-138)."""

import json
import sys

from finans.api.app import openapi_document


def render() -> str:
    return json.dumps(openapi_document(), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    sys.stdout.write(render())


if __name__ == "__main__":
    main()
