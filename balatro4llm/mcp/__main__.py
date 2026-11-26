"""Module entrypoint: python -m balatro4llm.mcp ..."""

import sys
from balatro4llm.mcp.server import main

if __name__ == "__main__":
    sys.exit(main())
