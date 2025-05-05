import os
import socket
import select
import threading
from battleship import Board, parse_coordinate, SHIPS, BOARD_SIZE

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
        send(wfiles[c], "[INFO] Game over. You may /chat or type quit to exit.")
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
                other = conns[1 - conns.index(sock)]
                send(wfiles[other], f"[CHAT] Player {sender_id}: {msg}")
            else:
                send(wfiles[sock], "[INFO] Game over: use /chat or quit to exit.")


def handle_game(p1_conn, p2_conn):
    conns = [p1_conn, p2_conn]
    rfiles = {c: c.makefile('r') for c in conns}
    wfiles = {c: c.makefile('w') for c in conns}

    # === Ship Placement Phase ===
    boards = [Board(), Board()]
    for idx, conn in enumerate(conns):
        send(wfiles[conn], "[REQUEST_PLACEMENT]")
        # read GRID_SIZE rows of placement
        temp = [ ['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE) ]
        for r in range(BOARD_SIZE):
            row = rfiles[conn].readline().strip().split()
            boards[idx].hidden_grid[r] = row
            temp[r] = row.copy()
        # reconstruct placed_ships
        boards[idx].placed_ships = []
        for ship_name, ship_size in SHIPS:
            placed = False
            for i in range(BOARD_SIZE):
                for j in range(BOARD_SIZE):
                    # horizontal
                    if j + ship_size <= BOARD_SIZE and all(temp[i][j+k] == 'S' for k in range(ship_size)):
                        pos = {(i, j+k) for k in range(ship_size)}
                        boards[idx].placed_ships.append({'name': ship_name, 'positions': pos})
                        for (rr,cc) in pos: temp[rr][cc] = '.'
                        placed = True
                        break
                    # vertical
                    if i + ship_size <= BOARD_SIZE and all(temp[i+k][j] == 'S' for k in range(ship_size)):
                        pos = {(i+k, j) for k in range(ship_size)}
                        boards[idx].placed_ships.append({'name': ship_name, 'positions': pos})
                        for (rr,cc) in pos: temp[rr][cc] = '.'
                        placed = True
                        break
                if placed: break
            if not placed:
                raise ValueError(f"Invalid placement: missing {ship_name}")

    # send back placements and IDs
    for idx, conn in enumerate(conns):
        send_ship_grid(wfiles[conn], boards[idx])
        send(wfiles[conn], f"[INFO] You are Player {idx+1}.")

    # === Main Game Loop ===
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
                # chat
                if line.startswith("[CHAT]"):
                    sender_id = conns.index(sock) + 1
                    msg = line[len("[CHAT]"):].strip()
                    target = defender if sock is attacker else attacker
                    send(wfiles[target], f"[CHAT] Player {sender_id}: {msg}")
                    continue
                # attack
                if sock is attacker:
                    try:
                        r, c = parse_coordinate(line)
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
                        # update views
                                                # UPDATE BOTH BOARDS
                        send_ship_grid(wfiles[defender], boards[1 - turn_idx])  # defender sees updated hidden grid
                        send_board(wfiles[attacker], boards[1 - turn_idx]) 
                        # win check
                        if sunk and defender_board.all_ships_sunk():
                            send(wfiles[attacker], "[END] You WIN! Fleet destroyed.")
                            send(wfiles[defender], "[END] You LOSE! Fleet destroyed.")
                            chat_only_phase(rfiles, wfiles, conns)
                            return
                        # next turn
                        turn_idx = 1 - turn_idx
                    except Exception as e:
                        send(wfiles[attacker], f"Invalid input: {e}")
                    break
                else:
                    send(wfiles[sock], "[INFO] Not your turn. Use /chat.")
                    continue
            else:
                continue
            break


def matchmaking_loop():
    print(f"[INFO] Server listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
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
