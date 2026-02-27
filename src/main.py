"""
Entrypoint: python -m src.main run --pdf ... --template ... --out ...
"""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()

from src.cli.app import app

if __name__ == "__main__":
    app()
