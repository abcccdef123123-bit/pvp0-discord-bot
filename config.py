import json
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def _int_env(name: str, required: bool = True) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        if required:
            raise RuntimeError(f"Brak wymaganej zmiennej środowiskowej: {name}")
        return None
    return int(raw)


TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("Ustaw DISCORD_TOKEN w pliku .env")

GUILD_ID = _int_env("GUILD_ID", required=False) or 1541920890328059994
VERIFIED_ROLE_ID = _int_env("VERIFIED_ROLE_ID", required=False)
STAFF_ROLE_ID = _int_env("STAFF_ROLE_ID", required=False)
TICKET_CATEGORY_ID = _int_env("TICKET_CATEGORY_ID", required=False)
LOG_CHANNEL_ID = _int_env("LOG_CHANNEL_ID", required=False)
CLAN_ROLE_ID = _int_env("CLAN_ROLE_ID", required=False)
ALLIANCE_ROLE_ID = _int_env("ALLIANCE_ROLE_ID", required=False)
ALLIANCE_LEADER_ROLE_ID = _int_env("ALLIANCE_LEADER_ROLE_ID", required=False)
APPROVAL_ROLE_1_ID = _int_env("APPROVAL_ROLE_1_ID", required=False)
APPROVAL_ROLE_2_ID = _int_env("APPROVAL_ROLE_2_ID", required=False)
TREASURY_LOG_CHANNEL_ID = _int_env("TREASURY_LOG_CHANNEL_ID", required=False)
ANNOUNCEMENTS_CHANNEL_ID = _int_env("ANNOUNCEMENTS_CHANNEL_ID", required=False)


def load_custom_settings() -> dict[str, int]:
    """Wczytuje niestandardowe ustawienia z data/settings.json."""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {k: int(v) for k, v in data.items() if str(v).isdigit()}
    except Exception:
        return {}


def update_setting(key: str, value: int) -> None:
    """Zapisuje ustawienie w data/settings.json i natychmiast aktualizuje config."""
    os.makedirs(DATA_DIR, exist_ok=True)
    current = load_custom_settings()
    current[key] = value
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Błąd zapisu settings.json: {e}")
    globals()[key] = value


# Nadpisz wartościami zapisanymi w data/settings.json (jeśli istnieją)
_custom = load_custom_settings()
for _k, _v in _custom.items():
    if _k in globals():
        globals()[_k] = _v

# Kolory paneli ze screenów
COLOR_VERIFY = 0x3BA55D
COLOR_TICKET = 0x1D4ED8
COLOR_RECRUIT = 0x38BDF8
COLOR_CLOSE = 0xED4245
COLOR_SUCCESS = 0x57F287
COLOR_ALLIANCE = 0xF59E0B
COLOR_RANK = 0x9333EA

# Kolory dla zbiórek i skarbca
COLOR_ALARM = 0xE03E3E
COLOR_TREASURY = 0xFFA500
COLOR_DEPOSIT = 0x2ECC71

FOOTER_TEXT = "Made by Aronek"
FOOTER_TEXT_ZBIORKA = "Made by Aronek • Gildia PVP0"

BANNER_PATH = os.path.join(BASE_DIR, "pvp0.gif")
if not os.path.exists(BANNER_PATH):
    BANNER_PATH = os.path.join(BASE_DIR, "assets", "pvp0.gif")
