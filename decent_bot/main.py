from codequest22.server.ant import AntTypes
import codequest22.stats as stats
from codequest22.server.events import DepositEvent, DieEvent, ProductionEvent, ZoneActiveEvent, ZoneDeactivateEvent
from codequest22.server.requests import GoalRequest, SpawnRequest
import random
import datetime
import json
import heapq
from scipy.stats import zscore
import numpy as np

log_file = "log"
LOG_PATH = f"{log_file}.txt"
# create the log files
with open(LOG_PATH, 'w'):
    pass

def get_team_name():
    return f"Decent Bot"

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
MAX_ANTS = 85
ACTIVE_HILL = False
ACTIVE_HILL_LOCATION = (1,1)

F_IDS = iter([f"f{i}" for i in range(100000)])
W_IDS = iter([f"w{i}" for i in range(100000)])
S_IDS = iter([f"s{i}" for i in range(100000)])

ACTIVE_ANTS = set()

TICKS = 0
DIST_OTHERS = []
CURR_REQUESTS = []

# Energy Scoring Parameters
OURS_MULTIPLIER = 15
OVERCHARGED_MULTIPLIER = 1.5
FOOD_SCORED = []

# Mapping every point to a number
ADJ = {}
IDX = {}
# A list of all points in the grid
POINTS = [] 

WORKERS_TO_FIGHTERS = 3 # Energy Strat: worker to fighter ratio

def djikstra_setup():
    """initiates the important vars djikstaras needs, only need to be run once!"""
    global ADJ, IDX, POINTS
    # Step 1: Generate edges - for this we will just use orthogonally connected cells.
    h, w = len(MAP_DATA), len(MAP_DATA[0])
    counter = 0
    for y in range(h):
        for x in range(w):
            ADJ[(x, y)] = []
            if MAP_DATA[y][x] == "W": continue
            POINTS.append((x, y))
            IDX[(x, y)] = counter
            counter += 1
    for x, y in POINTS:
        for a, b in [(y+1, x), (y-1, x), (y, x+1), (y, x-1)]:
            if 0 <= a < h and 0 <= b < w and MAP_DATA[a][b] != "W":
                ADJ[(x, y)].append((b, a, 1))

def djikstras(startpoint) -> dict:
    """RETURNS THE DISTANCE DICT"""
    global ADJ, IDX, POINTS
    # Dijkstra's Algorithm: Find the shortest path from your spawn to each FOOD zone.
    distance = {}
    # Step 2: Run Dijkstra's
    # What nodes have we already looked at?
    expanded = [False] * len(POINTS)
    # What nodes are we currently looking at?
    queue = []
    # What is the DISTANCE to the startpoint from every other point?
    heapq.heappush(queue, (0, startpoint))
    while queue:
        d, (a, b) = heapq.heappop(queue)
        if expanded[IDX[(a, b)]]: continue
        # If we haven't already looked at this point, put it in expanded and update the DISTANCE.
        expanded[IDX[(a, b)]] = True
        distance[(a, b)] = d
        # Look at all neighbours
        for j, k, d2 in ADJ[(a, b)]:
            if not expanded[IDX[(j, k)]]:
                heapq.heappush(queue, (
                    d + d2,
                    (j, k)
                ))
    return distance

def log(objs: dict = {}, level="INFO", txt=False):
    log_obj = {
        "LEVEL": level,
        "TIME": datetime.datetime.now().strftime("%H:%M:%S.%f"),
        "TICK": TICKS
    }
    log_obj.update(objs)
    with open(LOG_PATH, 'a') as log_file:
        if not txt:
            log_file.write(json.dumps(log_obj))
        else:
            log_file.write(f'TXT LINE: {txt}')
        log_file.write('\n')

def choose_food(overcharged=None):
    if TICKS < 150:
        return random.choices(FOOD, weights=FOOD_SCORED*6)[0]
    return random.choices(FOOD, weights=FOOD_SCORED)[0]

def num_workers() -> int:
    if MY_ENERGY > 290: 
        x = 290
    else:
        x = MY_ENERGY
    
    return round(np.exp(3-0.001*x)-15)

def read_map(md, energy_info):
    global MAP_DATA, SPAWNS, FOOD, DISTANCE, HILL, DIST_OTHERS, FOOD_SCORED
    MAP_DATA = md
    for y in range(len(MAP_DATA)):
        for x in range(len(MAP_DATA[0])):
            if MAP_DATA[y][x] == "F":
                FOOD.append((x, y))
            elif MAP_DATA[y][x] == "Z":
                HILL.append((x, y))
            if MAP_DATA[y][x] in "RBYG":
                SPAWNS["RBYG".index(MAP_DATA[y][x])] = (x, y)
    
    djikstra_setup()
    
    # Read map is called after read_index
    startpoint = SPAWNS[my_index]
    DISTANCE = djikstras(startpoint)
    DIST_OTHERS = [djikstras(team) for team in SPAWNS if team != startpoint]

    # BASE FOOD SCORE CALCULATION
    FOOD_DIST_US = [DISTANCE[i] for i in FOOD]
    FOOD_DIST_OTH_MIN = [min([DIST_OTHERS[team][i] for team in range(3)]) for i in FOOD]
    FOOD_DIST_OTH_AVG = [np.mean([DIST_OTHERS[team][i] for team in range(3)]) for i in FOOD]

    FOOD_SCORED = zscore(FOOD_DIST_US) * -OURS_MULTIPLIER + zscore(FOOD_DIST_OTH_MIN) + 0.8*zscore(FOOD_DIST_OTH_AVG)
    FOOD_SCORED = FOOD_SCORED - FOOD_SCORED.min() # scaling to get rid of negatives

    HILL = list(sorted(HILL, key=lambda prod: DISTANCE[prod]))

def handle_failed_requests(requests):
    global MY_ENERGY
    for req in requests:
        if req.player_index == my_index:
            print(f"Request {req.__class__.__name__} failed. Reason: {req.reason}.")
            log({"Request": req.__class__.__name__, "Reason": req.reason}, level = "ERROR")
            raise ValueError()

def handle_events(events):
    global MY_ENERGY, TOTAL_ANTS, FOOD, HILL, TICKS, ACTIVE_ANTS, F_IDS, S_IDS, W_IDS, CURR_REQUESTS, MAX_ANTS, ACTIVE_HILL, ACTIVE_HILL_LOCATION
    TICKS += 1

    CURR_REQUESTS = []

    for ev in events:
        if isinstance(ev, DepositEvent):
            if ev.player_index == my_index:
                # One of my worker ants just made it back to the Queen! Let's send them back to the FOOD site.
                CURR_REQUESTS.append(GoalRequest(ev.ant_id, choose_food()))
                # Additionally, let's update how much energy I've got.
                MY_ENERGY = ev.cur_energy
        elif isinstance(ev, ProductionEvent):
            if ev.player_index == my_index:
                # One of my worker ants just made it to the FOOD site! Let's send them back to the Queen.
                CURR_REQUESTS.append(GoalRequest(ev.ant_id, SPAWNS[my_index]))
        elif isinstance(ev, DieEvent):
            if ev.player_index == my_index:
                # One of my workers just died :(
                TOTAL_ANTS -= 1
                ACTIVE_ANTS.discard(ev.ant_id)
        elif isinstance(ev, ZoneActiveEvent):
            ACTIVE_HILL_LOCATION = ev.points[0]
            ACTIVE_HILL = True
            log({"HILL ACTIVATED": ACTIVE_HILL_LOCATION})
        elif isinstance(ev, ZoneDeactivateEvent):
            ACTIVE_HILL = False
            log({"HILL DEACTIVATED": ACTIVE_HILL_LOCATION})


    if not ACTIVE_HILL:
        # if no active zones
        allowed_ants = MAX_ANTS - len(ACTIVE_ANTS)

        n_workers = min(allowed_ants, num_workers())
        n_fighters = min(stats.general.MAX_SPAWNS_PER_TICK - n_workers, allowed_ants - n_workers)
        
        for _ in range(n_workers):
            worker_destination = choose_food()
            spawn_ant('worker', worker_destination, lg=True)
        
        for _ in range(n_fighters):
            worker_destination = choose_food()
            spawn_ant('fighter', worker_destination, lg=True)
        
    else:
        # if active zones 3 settlers, 1 fighter, 1 worker or 4,1
        settler_destination = ACTIVE_HILL_LOCATION
        worker_destination = choose_food()
        if MY_ENERGY > 300:
            for _ in range(4):
                spawn_ant('settler', settler_destination, lg=True)
            spawn_ant('fighter', settler_destination, lg=True)
        else:
            for _ in range(3):
                spawn_ant('settler', settler_destination, lg=True)
            spawn_ant('worker', worker_destination, lg=True)
            spawn_ant('fighter', settler_destination, lg=True)

    return CURR_REQUESTS

def spawn_ant(typ, goal, lg=False):
    global TOTAL_ANTS, MY_ENERGY, W_IDS, F_IDS, S_IDS, ACTIVE_ANTS, CURR_REQUESTS
    
    if TOTAL_ANTS < stats.general.MAX_ANTS_PER_PLAYER:
        if typ == 'worker':
            if MY_ENERGY >= stats.ants.Worker.COST:
                worker_id = next(W_IDS)
                ACTIVE_ANTS.add(worker_id)
                TOTAL_ANTS += 1
                CURR_REQUESTS.append(SpawnRequest(AntTypes.WORKER, id=worker_id, color=None, goal=goal))
                if lg: log({"SPAWN": f"1x {typ} ant, goal {goal}"})
                MY_ENERGY -= stats.ants.Worker.COST
                return
            else:
                log({"SPAWN_ERROR": f"Not enough energy to spawn worker: {MY_ENERGY}"})
        elif typ == 'fighter':
            if MY_ENERGY >= stats.ants.Fighter.COST:
                fighter_id = next(W_IDS)
                ACTIVE_ANTS.add(fighter_id)
                TOTAL_ANTS += 1
                CURR_REQUESTS.append(SpawnRequest(AntTypes.FIGHTER, id=fighter_id, color=None, goal=goal))
                if lg: log({"SPAWN": f"1x {typ} ant, goal {goal}"})
                MY_ENERGY -= stats.ants.Fighter.COST
                return
            else:
                log({"SPAWN_ERROR": f"Not enough energy to spawn fighter: {MY_ENERGY}"})
        elif typ == 'settler':
            if MY_ENERGY >= stats.ants.Settler.COST:
                settler_id = next(W_IDS)
                ACTIVE_ANTS.add(settler_id)
                TOTAL_ANTS += 1
                CURR_REQUESTS.append(SpawnRequest(AntTypes.SETTLER, id=settler_id, color=None, goal=goal))
                if lg: log({"SPAWN": f"1x {typ} ant, goal {goal}"})
                MY_ENERGY -= stats.ants.Settler.COST
                return
            else:
                log({"SPAWN_ERROR": f"Not enough energy to spawn settler: {MY_ENERGY}"})
    else:
        log({"SPAWN_ERROR": f"total ants: {TOTAL_ANTS} >= {stats.general.MAX_ANTS_PER_PLAYER}"})
    


## TODO
# Fix IDs
# Overcharged food in calc
# Send fighters
# Implement settling strategy
# Attacking/Defending?