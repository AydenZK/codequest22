from codequest22.server.ant import AntTypes
import codequest22.stats as stats
from codequest22.server.events import DepositEvent, DieEvent, ProductionEvent
from codequest22.server.requests import GoalRequest, SpawnRequest
import random
import datetime
import json

ENERGY_COMBOS = {
    'n5': {'n': 0.5, 'm': 1},
    'n6': {'n': 0.6, 'm': 1},
    3: {'n': 0.7, 'm': 1},
    4: {'n': 0.8, 'm': 1},
}
log_file = "n5"
LOG_PATH = log_file+".txt"
# create the log files
with open(LOG_PATH, 'w'):
    pass

def get_team_name():
    return f"Fighter Bot"

my_index = None
def read_index(player_index, n_players):
    global my_index
    my_index = player_index

MY_ENERGY = stats.general.STARTING_ENERGY
MAP_DATA = {}
SPAWNS = [None]*4
FOOD = []
HILL = []
DISTANCE = {}
TOTAL_ANTS = 0
SETTLER_COLOUR = (77,1,1)
FIGHTER_COLOUR = "#DE21DB"
TICKS = 0

ES_W_TO_F: 5 # Energy Strat: worker to fighter ratio

def log(objs: dict = {}, level="INFO"):
    log_obj = {
        "LEVEL": level,
        "TIME": datetime.datetime.now().strftime("%H:%M:%S.%f"),
        "TICK": TICKS
    }
    log_obj.update(objs)
    with open(LOG_PATH, 'a') as log_file:
        log_file.write(json.dumps(log_obj))
        log_file.write('\n')
        

def read_map(md, energy_info):
    global MAP_DATA, SPAWNS, FOOD, DISTANCE, HILL
    MAP_DATA = md
    for y in range(len(MAP_DATA)):
        for x in range(len(MAP_DATA[0])):
            if MAP_DATA[y][x] == "F":
                FOOD.append((x, y))
            elif MAP_DATA[y][x] == "Z":
                HILL.append((x, y))
            if MAP_DATA[y][x] in "RBYG":
                SPAWNS["RBYG".index(MAP_DATA[y][x])] = (x, y)
    # Read map is called after read_index
    startpoint = SPAWNS[my_index]
    # Dijkstra's Algorithm: Find the shortest path from your spawn to each FOOD zone.
    # Step 1: Generate edges - for this we will just use orthogonally connected cells.
    adj = {}
    h, w = len(MAP_DATA), len(MAP_DATA[0])
    # A list of all points in the grid
    points = []
    # Mapping every point to a number
    idx = {}
    counter = 0
    for y in range(h):
        for x in range(w):
            adj[(x, y)] = []
            if MAP_DATA[y][x] == "W": continue
            points.append((x, y))
            idx[(x, y)] = counter
            counter += 1
    for x, y in points:
        for a, b in [(y+1, x), (y-1, x), (y, x+1), (y, x-1)]:
            if 0 <= a < h and 0 <= b < w and MAP_DATA[a][b] != "W":
                adj[(x, y)].append((b, a, 1))
    # Step 2: Run Dijkstra's
    import heapq
    # What nodes have we already looked at?
    expanded = [False] * len(points)
    # What nodes are we currently looking at?
    queue = []
    # What is the DISTANCE to the startpoint from every other point?
    heapq.heappush(queue, (0, startpoint))
    while queue:
        d, (a, b) = heapq.heappop(queue)
        if expanded[idx[(a, b)]]: continue
        # If we haven't already looked at this point, put it in expanded and update the DISTANCE.
        expanded[idx[(a, b)]] = True
        DISTANCE[(a, b)] = d
        # Look at all neighbours
        for j, k, d2 in adj[(a, b)]:
            if not expanded[idx[(j, k)]]:
                heapq.heappush(queue, (
                    d + d2,
                    (j, k)
                ))
    # Now I can calculate the closest FOOD site.
    FOOD = list(sorted(FOOD, key=lambda prod: DISTANCE[prod]))
    HILL = list(sorted(HILL, key=lambda prod: DISTANCE[prod]))

def get_food_goal(n, m):
    """ Returns which food source an ant should go to
    (1-m) = prob that it will go to 3rd closest
    (m-n) = prob that it will go to 2nd closest
    n = prob that it will go to the closest
    """
    x = random.random()
    if x > m:
        return FOOD[2]
    if x > n:
        return FOOD[1]
    return FOOD[0]

def handle_failed_requests(requests):
    global MY_ENERGY
    for req in requests:
        if req.player_index == my_index:
            print(f"Request {req.__class__.__name__} failed. Reason: {req.reason}.")
            log({"Request": req.__class__.__name__, "Reason": req.reason}, level = "ERROR")
            raise ValueError()

def handle_events(events):
    global MY_ENERGY, TOTAL_ANTS, FOOD, HILL, SETTLER_COLOUR, TICKS
    TICKS += 1

    requests = []

    for ev in events:
        if isinstance(ev, DepositEvent):
            if ev.player_index == my_index:
                # One of my worker ants just made it back to the Queen! Let's send them back to the FOOD site.
                requests.append(GoalRequest(ev.ant_id, get_food_goal(n=0.85, m=1)))
                # Additionally, let's update how much energy I've got.
                MY_ENERGY = ev.cur_energy
        elif isinstance(ev, ProductionEvent):
            if ev.player_index == my_index:
                # One of my worker ants just made it to the FOOD site! Let's send them back to the Queen.
                requests.append(GoalRequest(ev.ant_id, SPAWNS[my_index]))
        elif isinstance(ev, DieEvent):
            if ev.player_index == my_index:
                # One of my workers just died :(
                TOTAL_ANTS -= 1

    # Can I spawn ants?
    spawned_this_tick = 0
    n_val = 0.7
    m_val = 0.95
    
    while (
        TOTAL_ANTS < stats.general.MAX_ANTS_PER_PLAYER and 
        spawned_this_tick < stats.general.MAX_SPAWNS_PER_TICK and
        MY_ENERGY >= stats.ants.Worker.COST
    ):
        spawned_this_tick += 1
        TOTAL_ANTS += 1
        # Spawn an ant, give it some id, no color, and send it to the closest site.
        # I will pay the base cost for this ant, so cost=None.
 
        requests.append(SpawnRequest(AntTypes.WORKER, id=None, color=None, goal=get_food_goal(**ENERGY_COMBOS[log_file])))
        MY_ENERGY -= stats.ants.Worker.COST

    ld = {"energy": MY_ENERGY}
    ld.update(ENERGY_COMBOS[log_file])
    log(ld)


    return requests
