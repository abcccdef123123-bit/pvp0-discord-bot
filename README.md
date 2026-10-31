# PVP0 · Bot Discord (weryfikacja + tickety)

Bot w **discord.py 2** dla klanu Minecraft. Odtwarza panele ze screenów: zieloną weryfikację i tickety z rozwijanym menu oraz formularzem rekrutacji.

## Funkcje

- Panel **weryfikacji** — zielony embed i przycisk `✅ Zweryfikuj się`
- Panel **ticketów** — dropdown `Dokonaj wyboru` (Pomoc techniczna / Rekrutacja / Inne)
- **Modal rekrutacji**: nick MC, wiek, staż — odpowiedzi lądują w tickecie
- Limit **jednego** otwartego ticketa na osobę
- Przycisk zamknięcia ticketa + opcjonalne logi

## Konfiguracja

1. Utwórz bota na [Discord Developer Portal](https://discord.com/developers/applications).
2. Włącz **Privileged Gateway Intent → Server Members Intent**.
3. Zaproś bota z uprawnieniami: `Manage Roles`, `Manage Channels`, `Send Messages`, `Embed Links`, `Attach Files`, `Use Slash Commands`.
4. Rola bota musi być **powyżej** roli weryfikowanej.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Uzupełnij `.env`:

| Zmienna | Opis |
|---|---|
| `DISCORD_TOKEN` | Token bota |
| `GUILD_ID` | ID serwera |
| `VERIFIED_ROLE_ID` | Rola po kliknięciu weryfikacji |
| `STAFF_ROLE_ID` | Rola administracji w ticketach |
| `TICKET_CATEGORY_ID` | Kategoria na kanały ticketów |
| `LOG_CHANNEL_ID` | (opcjonalnie) logi zamknięć |

## Uruchomienie

```powershell
python bot.py
```

Na kanale (jako administrator):

- `/panel-weryfikacja`
- `/panel-tickety`

Widoki są trwałe — po restarcie bota przyciski i menu dalej działają.
