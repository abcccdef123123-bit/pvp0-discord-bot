"""
Punkt startowy dla platform hostingowych (np. Bot-Hosting.net),
które domyślnie uruchamiają plik main.py.
"""
import asyncio
from bot import main

if __name__ == "__main__":
    asyncio.run(main())
