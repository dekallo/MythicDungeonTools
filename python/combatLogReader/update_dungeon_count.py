import os
import re
import pandas as pd
from get_wowtools_data import *
from CombatLogReader import get_count_table, get_total_count

expansions = ['Legion', 'BattleForAzeroth', 'Shadowlands']
# How to use:
# 1. Update the list "expansions" above to include all expansions. Use name of MDT expansion dungeon folders.
# 2. Delete the following files from the directory
#       uimapassignment.csv, map.csv, criteria.csv, criteriatree.csv, journalencounter.csv
# 3. Run the script, it writes directly to the files automatically.


# Takes as input an npcid
# If mob is in non-standard mob table output converted id
def npcid_to_event_asset(npcid, mob_count):
    # converter should have the MDT npcid as key and the GameEvent Asset id as value
    converter = {
        138489: 64192,      # Shadow of Zul, Kings' Rest
        68819: 63453,       # Eye of Sethraliss, Temple of Sethraliss
    }
    if npcid in converter.keys() and len(mob_count[mob_count.index == converter[npcid]]) > 0:

        return mob_count[mob_count.index == converter[npcid]].values[0][0]
    else:
        return 0


# Takes as input the regex match of a single mob and its count found in dungeon.lau MDT file,
# as well as true count for db file
# Outputs updated string
def update_count(match, mob_count):
    # keys will be 'id' and 'count'
    info = {match.group(1): int(match.group(2)), match.group(3): int(match.group(4))}
    if len(mob_count[mob_count.index == info['id']]) > 0:
        true_count = mob_count[mob_count.index == info['id']].values[0][0]
    else:
        true_count = npcid_to_event_asset(info['id'], mob_count)
    if true_count != info['count']:
        npc_name = pattern_npc_name.search(match.group()).group(1)
        print(f"    {npc_name} with id {info['id']} has been updated: {info['count']} -> {true_count}")
        return match.group().replace(f'["count"] = {info["count"]}', f'["count"] = {true_count}')

    # print(match.group())
    return match.group()


# Takes as input the regex match of current count found in dungeon.lau MDT file, as well as true count from db file
# Outputs updated string
def update_total_count(match, total_count):
    if total_count != int(match.group(1)):
        print(f"    Total dungeon count has been updated: {match.group(1)} -> {total_count}")
        return match.group().replace(f'normal={match.group(1)}', f'normal={total_count}')

    return match.group()


# Takes as input the text from a dungeon.lua MDT file and finds the dungoen associated with the file
def get_dungeon_from_file_text(file_text):
    pattern_encounterID = re.compile(r"encounterID\D*([\d]+)")
    encounterIDs = pattern_encounterID.findall(file_text)
    encounterIDs = [int(ID) for ID in encounterIDs]
    DungeonEncounterIDs = f['journalencounter'][f['journalencounter'].ID.isin(encounterIDs)].DungeonEncounterID.values
    CriteriaIDs = f['criteria'][f['criteria'].Asset.isin(DungeonEncounterIDs)].ID.values
    ParentIDs = f['criteriatree'][f['criteriatree'].CriteriaID.isin(CriteriaIDs)].Parent.values

    challenge_at_end = f['criteriatree'][(f['criteriatree'].ID.isin(ParentIDs))
                             & (f['criteriatree'].Description_lang.str.endswith("Challenge"))
                             & (f['criteriatree'].Operator == 4)]
    
    challenge_contained = f['criteriatree'][(f['criteriatree'].ID.isin(ParentIDs))
                                     & (f['criteriatree'].Description_lang.str.contains("Challenge"))
                                     & (f['criteriatree'].Operator == 4)]
    if len(challenge_at_end) > 0:
        return challenge_at_end.ID.values[0]

    elif len(challenge_contained) > 0:
        return challenge_contained.ID.values[0]

    else:
        # Weird case where blizzard doesn't use the journalencounterid, but instead the npcID
        all_npcids = re.findall(r"\"id\"\] = (\d+)", file_text)
        all_npcids = [int(ID) for ID in all_npcids]
        CriteriaIDs = f['criteria'][f['criteria'].Asset.isin(all_npcids)].ID.values
        ParentIDs = f['criteriatree'][f['criteriatree'].CriteriaID.isin(CriteriaIDs)].Parent.values
        if len(f['criteriatree'][(f['criteriatree'].ID.isin(ParentIDs))
                                 & (f['criteriatree'].Description_lang.str.endswith("Challenge"))]) > 0:
            dungeonID = f['criteriatree'][(f['criteriatree'].ID.isin(ParentIDs)) & (
                f['criteriatree'].Description_lang.str.endswith("Challenge"))].ID.values[0]

            return dungeonID

        else:
            print("WARNING: NEW SHIT BLIZZARD BRAIN DISCOVERED")


# Takes the direct path to a dungeon.lua MDT file and updates the count for the mobs found in the file
def update_file(fullpath):
    with open(fullpath, "r") as file:
        file_text = file.read()
        # Dungeon name
        print(f'Verifying {pattern_dungeon_name.search(file_text).group(1)}.')

        # String containing only table MDT.dungeonEnemies[dungeonIndex]
        dungeon_enemies = pattern_dungeonEnemies.search(file_text)[0]
        # Get true mob count table
        true_mob_count = get_count_table(get_dungeon_from_file_text(file_text))
        # Replace old MDT.dungeonEnemies[dungeonIndex] with new string containing true count
        dungeon_enemies_true_count = pattern_enemy_match.sub(lambda match: update_count(match, true_mob_count), dungeon_enemies)

        # String containing only table MDT.dungeonTotalCount[dungeonIndex]
        total_count = pattern_dungeonTotalCount.search(file_text)[0]
        # Get true total count
        true_total_count = get_total_count(get_dungeon_from_file_text(file_text))
        # Replace old count value with new true count
        true_count_string = pattern_count_value.sub(lambda match: update_total_count(match, true_total_count), total_count)
        # print(true_count_string)

        updated_text = pattern_dungeonTotalCount.sub(true_count_string, file_text)
        updated_text = pattern_dungeonEnemies.sub(dungeon_enemies_true_count, updated_text)

    with open(fullpath, "w") as file:
        file.write(updated_text)



# Importing files from wow.tools. If the file is available in the directory it is read otherwise it is downloaded first
#   uimapassignment: contains information about the extent of a UiMapID on its base minimap file.
#       Which means it contains minimap coordinate points for the borders of the in-game map
#   map: contains UiMapIDs and their associated dungeons
#   criteria: contains information about which criteria a given npc triggers when dying in a mythic dungeon
#   criteriatree: contains information about which criteria from the above list is triggered when count is
#        attributed in a mythic dungeon as well as the amount of count attributed
#   journalencounter: contains the encounterID and instanceID for bosses which MDT stores
wowtools_files = ["criteria", "criteriatree", "journalencounter"]
f = {}
for file in wowtools_files:
    try:
        f[file] = pd.read_csv(f"{file}.csv")
    except FileNotFoundError:
        f[file] = get_latest_version(file)


# Locate dungeon
# Get "encounterID" from MDT dungeon.lua file
# Get DungeonEncounterID from journalencounter db by searching encounterID as ID
# Get CriteriaID for criteria db by searching for DungeonEncounterID as Asset
# Get Parent from CriteriaTree by searching for CriteriaID as CriteriaID
# There will be multiple parents, the correct ID will be the one where Description_lang contains "Challenge"
pattern_dungeon_name = re.compile(r'MDT\.dungeonList\[dungeonIndex\] = L\[\"([\w\S ]+)\"]')
pattern_dungeonEnemies = re.compile(r"MDT\.dungeonEnemies\[dungeonIndex\] = \{[\s\S]*};")
pattern_enemy_match = re.compile(r"{[\s\S]+?\"(id|count)\"\D*([\d]+).*[\s\S]+?\"(id|count)\"\D*([\d]+)[\s\S]+?}")
pattern_dungeonTotalCount = re.compile(r"MDT\.dungeonTotalCount\[dungeonIndex\] .*")
pattern_count_value = re.compile(r"normal=(\d+)")
pattern_npc_name = re.compile(r'\[\"name\"\] = "([^\n]+)";')

# Make sure initial working directory is MythicDungeonTools
while os.getcwd().__contains__("MythicDungeonTools") and not os.getcwd().endswith("MythicDungeonTools"):
    os.chdir('..')

# Loop through all expansions and dungeons and update count information
for expansion in expansions:
    dungeon_filenames = os.listdir(expansion)
    print(f"- {expansion}")
    for dungeon_filename in dungeon_filenames:
        if dungeon_filename.endswith(".lua") and dungeon_filename != "overrides.lua":
            file_path = os.path.join(os.getcwd(), expansion, dungeon_filename)
            update_file(file_path)

