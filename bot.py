"""
etherscan-mint-tx-tgbot, Etherscan Mint Transactions to Telegram
Copyright (C) 2021  Dash Eclipse

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.


Etherscan Mint Transactions to Telegram (etherscan-mint-tx-tgbot)
-----------------------------------------------------------------

Monitor Ethereum mint transaction of specific addresses through
Etherscan.io and send to Telegram

I asked Etherscan Team about how to get "Transaction Action" info as
shown in transaction details webpage through Etherscan API, and they
told me it's not possible at the moment (2021-09-11).

> We unfortunately do not have an endpoint that returns the
> "Transaction Action" information at this point of time.
>
> It is a popular one by request, and we will definitely consider to
> add it in a future update.

So this implementation checks new transactions through Etherscan API,
and check if new transactions include "Mint" in transaction action by
parsing transaction details webpage.


Setup
-----

pip3 install -U Pyrogram TgCrypto etherscan-python beautifulsoup4
python3 bot.py


Commands
--------

/start addr name
/stop addr
/help


Changelogs
----------

2021-09-16: feat: initial version for public release
"""
import asyncio
from os import path
from datetime import datetime as dt
from typing import Optional
import json

import requests
from etherscan import Etherscan
from pyrogram import Client, filters, idle, emoji
from pyrogram.types import Message
from bs4 import BeautifulSoup

# Configuration
# Get API_ID and API_HASH from https://my.telegram.org/apps
API_ID = 1234567
API_HASH = "0123456789abcdef0123456789abcdef"
# Create bot and get bot token from https://t.me/BotFather
BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
# user/group/channel ID or username to send update to
# e.g. "username" or -100123456789
TG_CHAT = "username"
TG_BOT_OWNER = "username"
# Etherscan API token, get your API key at https://etherscan.io/myapikey
ETHERSCAN_TOKEN = "ABCDEFGHIJKLMNOPQRSTUVWXYZ12345678"
# update interval in seconds
UPDATE_INTERVAL = 10
# True then fetch transaction page and check if it includes Mint action
# for every new transaction, False then save method ID and only check
# for transactions with unknown method IDs
ALWAYS_CHECK_TX_WEBPAGE = True

# Constants
main_filter = (
    filters.text
    & filters.incoming
    & filters.private
    & filters.chat(TG_BOT_OWNER)
    & ~filters.edited
)
DATA_FILE = path.join(
    path.dirname(path.realpath(__file__)),
    "data.json"
)
SOUP_SESSION = requests.Session()
SOUP_SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:89.0) '
    'Gecko/20100101 Firefox/89.0'
})


async def validate_mint_tx(tx):
    txhash = tx['hash']
    method_id = tx['input'][:10]
    if not ALWAYS_CHECK_TX_WEBPAGE:
        if method_id in data.get('methods', {}).get('exclude', {}):
            print(f'- excluded {method_id} for {txhash}')
            return False
        if method_id in data.get('methods', {}).get('include', {}):
            print('- included {method_id} for {txhash}')
            return True
    tx_url = f"https://etherscan.io/tx/{tx['hash']}"
    response = SOUP_SESSION.get(tx_url)
    if response.status_code != 200:
        print(f'- status code: {response.status_code}')
        return None
    soup = BeautifulSoup(response.text, 'html.parser')
    validity = bool(soup.body.findChildren(
        "span", {"class": "mr-1 d-inline-block"}, string="Mint of"
    ))
    if not ALWAYS_CHECK_TX_WEBPAGE:
        if validity:
            data['methods']['include'][method_id] = txhash
        else:
            data['methods']['exclude'][method_id] = txhash
    return validity


async def send_tx_msg(app, addr, tx):
    addr_name = data['addrs'].get(addr, {}).get('name', 'None')
    text = (
        f"{emoji.NEW_BUTTON} [{tx['hash'][:10]}]"
        + f"(https://etherscan.io/tx/{tx['hash']}) (**{addr_name}**)\n"
        + f"{emoji.CALENDAR} "
        + f"{dt.utcfromtimestamp(int(tx['timeStamp'])).strftime('%F %T')}\n"
        + f"{emoji.MONEY_BAG} {int(tx['value']) / 1000000000000000000} Ether\n"
    )
    await app.send_message(
        TG_CHAT,
        text,
        disable_web_page_preview=True
    )


async def send_transactions(app):
    while True:
        for addr in data['addrs']:
            old_startblock = data['addrs'].get(addr, {}).get('startblock', 0)
            try:
                txs = eth.get_normal_txs_by_address(
                    addr,
                    startblock=old_startblock,
                    endblock=99999999,
                    sort="asc"
                )
                for tx in txs:
                    valid_mint_tx = await validate_mint_tx(tx)
                    if valid_mint_tx:
                        await send_tx_msg(app, addr, tx)
                    elif valid_mint_tx is None:
                        print(f'- failed to check transaction: {tx}')
                data['addrs'][addr]['startblock'] = (
                    int(txs[-1]['blockNumber']) + 1
                )
            except AssertionError:  # No transactions found
                pass
            except json.decoder.JSONDecodeError:
                print('- UNHANDLED: JSON Decode Error')
                data['addrs'][addr]['startblock'] = old_startblock
            except Exception as e:
                print(f'- ERROR: {e}')
                data['addrs'][addr]['startblock'] = old_startblock
        await asyncio.sleep(UPDATE_INTERVAL)


async def get_last_blocknumber(addr: str) -> Optional[int]:
    try:
        txs = eth.get_normal_txs_by_address(
            addr,
            startblock=0,
            endblock=99999999,
            sort="asc"
        )
        return int(txs[-1]['blockNumber'])
    except (AssertionError, json.decoder.JSONDecodeError):
        return None


async def main():
    app = Client(
        "ethertg",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN
    )

    @app.on_message(main_filter & filters.command("start"))
    async def command_start(_, m: Message):
        len_cmd = len(m.command)
        if len_cmd == 1:
            addrs = "\n".join([
                f"\u2022 [{k}](https://etherscan.io/address/{k}) "
                + f"**{v['name']}**"
                for k, v in data['addrs'].items()
            ]) or 'None'
            text = (
                f"{emoji.ROBOT} **Etherscan Mint Transaction To Telegram**\n\n"
                "Monitored addresses:\n"
                + addrs
            )
        elif len_cmd >= 3:
            addr = m.command[1]
            startblock = await get_last_blocknumber(addr) + 1
            name = " ".join(m.command[2:])
            if startblock:
                data['addrs'][addr] = {
                    'name': name,
                    'startblock': startblock
                }
                text = f"Added new monitored address: `{addr}`"
            else:
                text = "The specified address is invalid"
        else:
            text = "Usage: /start addr name"
        await m.reply_text(text, quote=True, disable_web_page_preview=True)

    @app.on_message(main_filter & filters.command("stop"))
    async def command_stop(_, m: Message):
        if len(m.command) == 1:
            text = "Specify address to stop monitoring on it"
        else:
            addr = m.command[1]
            if addr in data.keys():
                addr_name = data['addrs'][addr]['name']
                data.pop(addr)
                text = (
                    f"{emoji.STOP_BUTTON} Successfully stopped "
                    "monitoring address: "
                    f"`{addr}` **{addr_name}**"
                )
            else:
                text = "The specified address is not in the list"
        await m.reply_text(text, quote=True)

    @app.on_message(main_filter & filters.command("help"))
    async def command_help(_, m: Message):
        text = (
            f"{emoji.INFORMATION} **Usage Info for "
            "Etherscan Mint Transaction to Telegram Bot**:\n\n"
            "\u2022 /start | __list monitored addresses__\n"
            "\u2022 /start addr name | __start monitoring a new address__\n"
            "\u2022 /stop addr | __stop monitoring an address__\n"
            "\u2022 /help | __show usage info__"
        )
        await m.reply_text(text)

    await app.start()
    await asyncio.create_task(send_transactions(app))
    await idle()


if __name__ == "__main__":
    eth = Etherscan(ETHERSCAN_TOKEN)
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {
            'addrs': {},
            'methods': {
                'include': {},
                'exclude': {}
            }
        }
    if not data:
        print('- no address been specified yet')
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f)
