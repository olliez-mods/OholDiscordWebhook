import yaml
import requests
import socket
import time
import json

from get_player_stats import get_bs2_player_status

settings = None
with open('settings.yaml', 'r') as ys:
    settings = yaml.safe_load(ys)

c_time = int(time.time())
sp_relative = f'<t:{c_time}:R>'
sp_full = f'<t:{c_time}:F>'

description = f'{sp_full}\nRemote servers ([URL LINK](https://onehouronelife.com/reflector/server.php?action=report)):\n'
total_players = 0
total_available = 0

bs2_extra_data = None
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

for server in settings['servers']:
    server_display = str(server)
    domain_to_trim = settings["domain_to_trim"]
    if(settings["trim_domain"] and server_display.endswith(domain_to_trim)):
        server_display = server_display[:-len(domain_to_trim)]

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect((server, 8005))
            s.settimeout(1)
            data = s.recv(1024).split()[1].split(b'/')
            data = [int(data[0]), int(data[1])]
            total_players += data[0]
            total_available += data[1]
            server_lines.append(f'|--> {server_display}{PORT_STRING} -> {data[0]} /{data[1]}')
    except socket.error as e:
        server_lines.append(f'|--> {server_display}{PORT_STRING} -> OFFLINE')
        print(e)

    # Attemp to get extra family data if enabled, and correct server
    if (bs2_extra_data == None and settings["use_bs2_bot"]):
        try:
            bs2_extra_data = get_bs2_player_status(settings["bs2_bot_token"], server)
        except Exception as e:
            print(e, "Error getting extra family data"); bs2_extra_data = None
        if(bs2_extra_data): bs2_server_ip = server

# Only the server rows get padded, the footer isn't a column-aligned row.
# Inside a code block: Discord's normal font is proportional, so spaces only
# line up as columns in monospace
server_table = pad_lines("\n".join(server_lines), [1, 3])
server_table = f'{server_table}\n---------------------------\nTotal ::: {total_players} / {total_available}'
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
    family_description = f"**Family data for `{bs2_server_ip}`:\n**"
    family_table = ""
    for family in bs2_extra_data.values():
        family_table = f"{family_table}{family['name']} - Pop:{family['count']}, Gen:{family['generation']}\n"
    family_table = f"```{pad_lines(family_table, [0, 2])}```"
    data["embeds"].append({
        "color": 16777215,
        "description": f"{family_description}{family_table}"
    })

if 'msg_id' in settings:
    r = requests.patch(f"{settings['webhook']}/messages/{settings['msg_id']}", json = data)
#    if r.status_code != 200:
#        settings.pop('msg_id')
#        with open('settings.yaml', 'w') as ys:
#            yaml.dump(settings, ys, default_flow_style = False)
else:
    settings['msg_id'] = json.loads(requests.post(f"{settings['webhook']}?wait=true", json = data).content.decode())['id']
    with open('settings.yaml', 'w') as ys:
        yaml.dump(settings, ys, default_flow_style = False)