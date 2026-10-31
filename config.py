import os
from dotenv import load_dotenv

load_dotenv()


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

GUILD_ID = _int_env("GUILD_ID")
VERIFIED_ROLE_ID = _int_env("VERIFIED_ROLE_ID")
STAFF_ROLE_ID = _int_env("STAFF_ROLE_ID")
TICKET_CATEGORY_ID = _int_env("TICKET_CATEGORY_ID")
LOG_CHANNEL_ID = _int_env("LOG_CHANNEL_ID", required=False)
CLAN_ROLE_ID = _int_env("CLAN_ROLE_ID", required=False)
ALLIANCE_ROLE_ID = _int_env("ALLIANCE_ROLE_ID", required=False)
ALLIANCE_LEADER_ROLE_ID = _int_env("ALLIANCE_LEADER_ROLE_ID", required=False)
APPROVAL_ROLE_1_ID = _int_env("APPROVAL_ROLE_1_ID", required=False)
APPROVAL_ROLE_2_ID = _int_env("APPROVAL_ROLE_2_ID", required=False)
TREASURY_LOG_CHANNEL_ID = _int_env("TREASURY_LOG_CHANNEL_ID", required=False)

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BANNER_PATH = os.path.join(BASE_DIR, "pvp0.gif")
if not os.path.exists(BANNER_PATH):
    BANNER_PATH = os.path.join(BASE_DIR, "assets", "pvp0.gif")
