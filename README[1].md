# BTC NY Opening Signal Bot

Automatische Bitcoin trading signalen via Telegram.

## Hoe het werkt
- Elke werkdag om 13:25 UTC (15:25 NL tijd)
- Analyseert CME gap, VIX, funding rate, fear index
- Stuurt LONG/SHORT/NO TRADE signaal naar je Telegram

## Setup
1. Fork deze repo
2. Ga naar Settings > Secrets and variables > Actions
3. Voeg toe:
   - `TELEGRAM_BOT_TOKEN` (van @BotFather)
   - `TELEGRAM_CHAT_ID` (van @userinfobot)
4. Klaar! De bot draait automatisch.

## Handmatig testen
Ga naar Actions > BTC NY Opening Signal > Run workflow
