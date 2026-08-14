import requests

BS2_SERVER = "bigserver2.onehouronelife.com"

def create_url(token:str):
    return f"http://yummy.antinoid.com/tutbot/api/get_players_live?token={token}&only_alive=1&hide_lineage=1"

"""
{
    "fam_name": {
        "name":"JOHNSS",
        "count":12,
        "generation":56
    }
}
"""
def get_bs2_player_status(token: str) -> dict | None:
    if(not token): raise Exception("Token must be present")
    url = create_url(token)
    r = requests.get(url, timeout = 10)
    r.raise_for_status()

    response = r.json()
    if("error" in response): raise ConnectionError("Error", response["error"])

    # Do some parsing
    result = {}

    for player in r.json():
        name = str(player.get("name"))
        if(" " not in name): continue # Doesn't have first and last name, or not provided, continue
        first, last = name.split()
        generation = player.get("generation_num")
        if(not generation):
            raise Exception("Generation not found in result")

        fam = result.get(last)
        if(not fam):
            if(player.get("age", 0) >= 59): continue # Don't count ghosts, if it's only them in the family
            result[last] = {"name":last, "count":0, "generation":0}
            fam = result[last]


        fam["count"] += 1
        fam["generation"] = max(fam["generation"], generation)

    return result