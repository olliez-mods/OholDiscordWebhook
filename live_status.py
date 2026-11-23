import sys
import requests
import json

from quick_ini import QuickIni

import server_cache
from get_player_stats import get_bs2_player_status, BS2_SERVER

# template=True adds any settings new to config.ini.template into config.ini
QuickIni.load_file('config.ini', template=True)
settings = QuickIni.get_all()

total_players = 0
total_available = 0

bs2_extra_data = None
bs2_error_data = None
bs2_server_ip = None

def pad_lines(multiline_str:str, parts, end_space:int = 0, split_by:str = " "):
    if(isinstance(parts, int)): parts = [parts]
    # Split every line once up front, so padding one column can't shift the
    # part indices seen by the next one
    lines = [line.split(split_by) for line in multiline_str.split("\n")]
    for part in parts:
        max_item_length = -1
        for line_parts in lines:
            if(part >= len(line_parts)): continue # Not enough parts in this line
            max_item_length = max(max_item_length, len(line_parts[part]))
        if(max_item_length < 0): continue # No line has this part
        for line_parts in lines:
            if(part >= len(line_parts)): continue # Not enough parts in this line
            if(part == len(line_parts) - 1): continue # Last part, would only add trailing space
            str_part = line_parts[part]
            line_parts[part] = str_part + " " * (max_item_length - len(str_part) + end_space)
    return "\n".join(split_by.join(line_parts) for line_parts in lines)

server_lines = []

PORT_STRING = ":8005" if (settings["show_port"]) else ""
JASON_REFLECTOR_URL = "https://onehouronelife.com/reflector/server.php?action=report"

# Shared with the other instances on this machine, so the servers get probed once per
# cycle however many of us cron starts at the same moment
# An entry made only of dashes (e.g. "|---" in config.ini) is a divider between server
# groups, not a host, so it is never probed
def is_separator(entry) -> bool:
    entry = str(entry).strip()
    return entry != "" and set(entry) == {"-"}

SEPARATOR_PLACEHOLDER = "<<separator>>"

probe_servers = [server for server in settings['servers'] if not is_separator(server)]
statuses = server_cache.get_statuses(probe_servers, settings)

# These numbers can be as old as the cache TTL, so stamp the embed with when they were
# actually gathered rather than with now
c_time = server_cache.oldest_timestamp(statuses, probe_servers)
sp_relative = f'<t:{c_time}:R>'
sp_full = f'<t:{c_time}:F>'

description = f'{sp_full}\nRemote servers ([URL LINK]({JASON_REFLECTOR_URL})):\n'

for server in settings['servers']:
    if(is_separator(server)):
        server_lines.append(SEPARATOR_PLACEHOLDER)
        continue
    server_display = str(server)
    domain_to_trim = settings["domain_to_trim"]
    if(settings["trim_domain"] and server_display.endswith(domain_to_trim)):
        server_display = server_display[:-len(domain_to_trim)]

    status = statuses[server]
    if(status["online"]):
        total_players += status["players"]
        total_available += status["capacity"]
        server_lines.append(f'|--> {server_display}{PORT_STRING} -> {status["players"]} /{status["capacity"]}')
    else:
        server_lines.append(f'|--> {server_display}{PORT_STRING} -> OFFLINE')

# Attemp to get extra family data if enabled, and we're tracking the BS2 server
if(settings["use_bs2_bot"] and BS2_SERVER in settings['servers']):
    try:
        bs2_extra_data = get_bs2_player_status(settings["bs2_bot_token"])
    except Exception as e:
        print(e, "Error getting extra family data");
        bs2_extra_data = None
        bs2_error_data = str(e)

server_table = pad_lines("\n".join(server_lines), [1, 3])
# Swapped in after padding so dividers span the padded server rows
table_width = max((len(line) for line in server_table.split("\n") if line != SEPARATOR_PLACEHOLDER), default=20)
server_table = server_table.replace(SEPARATOR_PLACEHOLDER, "|" + "-" * (table_width - 1))
server_table = f'{server_table}\n{"-"*table_width}\nTotal ::: {total_players} / {total_available}'
description = f'{description}```\n{server_table}\n```\n'
description = f'{description}Last update: {sp_relative}\n'

data = {
  "content": "",
  "embeds": [{
    "color": 16777215,
    "description": description
  }]
}

if(bs2_extra_data):
    family_description = f"**Family data for `{BS2_SERVER}`:\n**"
    family_lines = [
        f"{family['name']} - Pop:{family['count']}, Gen:{family['generation']}"
        for family in bs2_extra_data["families"].values()
    ]
    family_table = pad_lines("\n".join(family_lines), [0, 2])
    # Added after padding so the ghost line doesn't widen the family columns
    separator = "-" * max((len(line) for line in family_table.split("\n")), default=20)
    family_table = f"```{family_table}\n{separator}\nGhosts ::: {bs2_extra_data['ghosts']}```"
    data["embeds"].append({
        "color": 16777215,
        "description": f"{family_description}{family_table}"
    })
if(bs2_error_data):
    family_description = f"**Family data for `{BS2_SERVER}`:\n**"
    data["embeds"].append({
        "color" : 16711680,
        "description": f"```Could not fetch data```"
    })


# Only makes a new message when asked, and prints the id for you to paste into
# config.ini yourself
if(len(sys.argv) > 1 and sys.argv[1] == "create"):
    msg_id = json.loads(requests.post(f"{settings['webhook']}?wait=true", json = data).content.decode())['id']
    print(f"Created new message with id {msg_id}")
else:
    r = requests.patch(f"{settings['webhook']}/messages/{settings['msg_id']}", json = data)