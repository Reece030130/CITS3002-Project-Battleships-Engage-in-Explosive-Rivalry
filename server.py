import os
import socket
import select
import threading
from battleship import Board, parse_coordinate, SHIPS, BOARD_SIZE
from collections import deque
from collections import Counter
from itertools import combinations
from itertools import product

HOST = '127.0.0.1'
PORT = 5000

waiting_players = []
lock = threading.Lock()

def send(wfile, msg):
    wfile.write(msg + '\n')
    wfile.flush()

def send_board(wfile, board):
    wfile.write("GRID\n")
    wfile.write("  " + " ".join(str(i + 1).rjust(2) for i in range(board.size)) + "\n")
    for r in range(board.size):
        row_label = chr(ord('A') + r)
        row_str = " ".join(board.display_grid[r][c] for c in range(board.size))
        wfile.write(f"{row_label:2} {row_str}\n")
    wfile.write("\n")
    wfile.flush()

def send_ship_grid(wfile, board):   
    wfile.write("[SHIPS]\n")
    for r in range(board.size):
        wfile.write(" ".join(board.hidden_grid[r]) + "\n")
    wfile.write("\n")
    wfile.flush()

def chat_only_phase(rfiles, wfiles, conns):
    # After game end: notify and relay chat only
    for c in conns:
        send(wfiles[c], "[INFO] Game over. Chat or type /again to play again, or /quit to exit.")
    ready_again = [False, False]
    while True:
        ready, _, _ = select.select(conns, [], [])
        for sock in ready:
            line = rfiles[sock].readline()
            if not line:
                continue
            line = line.strip().lower()
            idx = conns.index(sock)
            if line == '/again':
                ready_again[idx] = True
                send(wfiles[sock],"[INFO] Waiting for opponent to accept rematch...")
                if all(ready_again):
                    # 关闭旧的 rfile/wfile 并重新创建
                    print("[INFO] Both players agreed to rematch. Starting new game...")
                    # 调用新一轮游戏
                    handle_game(conns[0], conns[1], rfiles, wfiles)
                    return
            elif line == 'quit' or line == '/quit':
                other = conns[1 - idx]
                send(wfiles[other], "[INFO] Opponent left. Returning to lobby.")
                waiting_players.append(other)
                return
            elif line.startswith("[chat]"):
                send(wfiles[conns[1 - idx]], f"[CHAT] Player {idx+1}: {line[6:]}")
            else:
                send(wfiles[sock], "[INFO] Type /again to rematch or /quit to exit.")

def get_connected_blocks(grid):
    visited = [[False]*BOARD_SIZE for _ in range(BOARD_SIZE)]
    blocks = []

    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if grid[r][c] == 'S' and not visited[r][c]:
                q = deque()
                q.append((r, c))
                visited[r][c] = True
                block = [(r, c)]
                while q:
                    x, y = q.popleft()
                    for dx, dy in [(0,1), (1,0), (0,-1), (-1,0)]:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and not visited[nx][ny] and grid[nx][ny] == 'S':
                            visited[nx][ny] = True
                            q.append((nx, ny))
                            block.append((nx, ny))
                blocks.append(block)
    return blocks


def try_assign_ships(lines, expected_sizes):

    expected_sizes = sorted(expected_sizes, reverse=True)
    used = set()

    def all_subsegments(line, size):
        if len(line) < size:
            return []
        return [line[i:i+size] for i in range(len(line) - size + 1)]

    def backtrack(index, chosen, used):
        if index == len(expected_sizes):
            return chosen
        size = expected_sizes[index]
        for line in lines:
            for segment in all_subsegments(line, size):
                if all(pos not in used for pos in segment):
                    new_used = used | set(segment)
                    result = backtrack(index + 1, chosen + [segment], new_used)
                    if result:
                        return result
        return None

    return backtrack(0, [], set())


def extract_ships(grid):
    expected_sizes = [size for _, size in SHIPS]
    lines = []

    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if grid[r][c] != 'S':
                continue

            # Horizontal ship start
            if c == 0 or grid[r][c - 1] != 'S':
                length = 0
                while c + length < BOARD_SIZE and grid[r][c + length] == 'S':
                    length += 1
                if length >= 2:
                    lines.append([(r, c + i) for i in range(length)])

            # Vertical ship start
            if r == 0 or grid[r - 1][c] != 'S':
                length = 0
                while r + length < BOARD_SIZE and grid[r + length][c] == 'S':
                    length += 1
                if length >= 2:
                    lines.append([(r + i, c) for i in range(length)])

    lines.sort(key=lambda x: -len(x))

    selected = try_assign_ships(lines, expected_sizes)
    if selected is None:
        raise ValueError(f"Invalid placement: could not form expected ships from lines {[len(l) for l in lines]}")

    return selected


def handle_game(p1_conn, p2_conn, rfiles=None, wfiles=None):

    conns = [p1_conn, p2_conn]

    if rfiles is None:
        rfiles = {c: c.makefile('r') for c in conns}
    if wfiles is None:
        wfiles = {c: c.makefile('w') for c in conns}

    # ✅ 无条件创建新棋盘（支持 rematch）
    boards = [Board(), Board()]

    # === Ship Placement Phase ===
    for idx, conn in enumerate(conns):
        while True:
            send(wfiles[conn], "[REQUEST_PLACEMENT]")
            temp = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
            for r in range(BOARD_SIZE):
                line = rfiles[conn].readline()
                if not line:
                    raise ConnectionError(f"Player {idx+1} disconnected during placement")
                row = line.strip().split()
                if len(row) != BOARD_SIZE:
                    raise ValueError(f"Row {r} has incorrect length: {row}")
                boards[idx].hidden_grid[r] = row
                temp[r] = row.copy()
            rfiles[conn].readline()  # 空行

            print(f"\n[DEBUG] Player {idx+1} board received:")
            for row in temp:
                print(' '.join(row))

            try:
                ships_found = extract_ships(temp)
                ship_lengths = sorted([len(s) for s in ships_found])
                print(f"[DEBUG] Player {idx+1} ships found: {ship_lengths}")

                expected_lengths = sorted([size for _, size in SHIPS])
                if Counter(ship_lengths) != Counter(expected_lengths):
                    raise ValueError(f"Invalid placement: wrong ship sizes {ship_lengths}, expected {expected_lengths}")

                remaining = Counter(expected_lengths)
                name_pool = {s: [name for name, sz in SHIPS if sz == s] for s in remaining}
                boards[idx].placed_ships = []
                for shape in ships_found:
                    sz = len(shape)
                    if remaining[sz] > 0:
                        if name_pool.get(sz) and name_pool[sz]:
                            name = name_pool[sz].pop()
                        else:
                            name = f"{sz}-ship-{remaining[sz]}"
                        boards[idx].placed_ships.append({'name': name, 'positions': set(shape)})
                        remaining[sz] -= 1
                    else:
                        raise ValueError(f"Unexpected ship of size {sz}")
                break
            except Exception as e:
                print(f"[ERROR] Player {idx+1} placement failed: {e}")
                send(wfiles[conn], f"[INFO] Invalid placement: {e}")

    # 返回结果给客户端
    for idx, conn in enumerate(conns):
        send_ship_grid(wfiles[conn], boards[idx])
        send(wfiles[conn], f"[INFO] You are Player {idx+1}.")

    # === Game Loop ===
    turn_idx = 0
    while True:
        attacker = conns[turn_idx]
        defender = conns[1 - turn_idx]
        defender_board = boards[1 - turn_idx]

        send(wfiles[attacker], f"[TURN] Your move, Player {turn_idx+1}.")

        while True:
            ready, _, _ = select.select(conns, [], [])
            for sock in ready:
                line = rfiles[sock].readline()
                if not line or line.strip().lower() == 'quit':
                    other = conns[1 - conns.index(sock)]
                    send(wfiles[other], "[EXIT] Server shutting down.")
                    os._exit(0)
                line = line.strip()
                if line.startswith("[CHAT]"):
                    sender_id = conns.index(sock) + 1
                    msg = line[len("[CHAT]"):].strip()
                    target = defender if sock is attacker else attacker
                    send(wfiles[target], f"[CHAT] Player {sender_id}: {msg}")
                    continue
                if sock is attacker:
                    try:
                        r, c = parse_coordinate(line)
                        if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
                            raise ValueError("wrong coordinates")
                        result, sunk = defender_board.fire_at(r, c)
                        if result == 'hit':
                            send(wfiles[attacker], f"HIT!{' You sank '+sunk+'!' if sunk else ''}")
                            send(wfiles[defender], f"[DEFENSE] Opponent hit at {line}.")
                        elif result == 'miss':
                            send(wfiles[attacker], "MISS!")
                            send(wfiles[defender], f"[DEFENSE] Opponent missed at {line}.")
                        else:
                            send(wfiles[attacker], "Already fired there. Try again.")
                            break
                        send_ship_grid(wfiles[defender], defender_board)
                        send_board(wfiles[attacker], defender_board)
                        if sunk and defender_board.all_ships_sunk():
                            send(wfiles[attacker], "[END] You WIN! Fleet destroyed.")
                            send(wfiles[defender], "[END] You LOSE! Fleet destroyed.")
                            chat_only_phase(rfiles, wfiles, conns)
                            return
                        turn_idx = 1 - turn_idx
                    except Exception as e:
                        send(wfiles[attacker], f"Invalid input: {e}")
                    break
                else:
                    send(wfiles[sock], "[INFO] Not your turn. Use /chat.")
            else:
                continue
            break


def matchmaking_loop():
    print(f"[INFO] Server listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        while True:
            conn, _ = s.accept()
            with lock:
                waiting_players.append(conn)
                if len(waiting_players) >= 2:
                    p1 = waiting_players.pop(0)
                    p2 = waiting_players.pop(0)
                    threading.Thread(target=handle_game, args=(p1, p2), daemon=True).start()

if __name__ == '__main__':
    matchmaking_loop()
