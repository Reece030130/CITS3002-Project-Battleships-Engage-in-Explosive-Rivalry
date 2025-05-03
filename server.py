import socket
import select
import threading
from battleship import Board, parse_coordinate

HOST = '127.0.0.1'
PORT = 5000

waiting_players = []
lock = threading.Lock()

def send(wfile, msg):
    wfile.write(msg + '\n')
    wfile.flush()

def send_board(wfile, board):
    wfile.write("GRID\n")
    wfile.write("  " + " ".join(str(i + 1).rjust(2) for i in range(board.size)) + '\n')
    for r in range(board.size):
        row_label = chr(ord('A') + r)
        row_str   = " ".join(board.display_grid[r][c] for c in range(board.size))
        wfile.write(f"{row_label:2} {row_str}\n")
    wfile.write('\n')
    wfile.flush()

def send_ship_grid(wfile, board):
    wfile.write("[SHIPS]\n")
    for r in range(board.size):
        wfile.write(" ".join(board.hidden_grid[r]) + "\n")
    wfile.write("\n")
    wfile.flush()

def handle_game(p1_conn, p2_conn):
    # wrap sockets in file-like objects
    conns  = [p1_conn, p2_conn]
    rfiles = {c: c.makefile('r') for c in conns}
    wfiles = {c: c.makefile('w') for c in conns}

    boards = [Board(), Board()]
    boards[0].place_ships_randomly()
    boards[1].place_ships_randomly()

    # initial ship layouts & info
    send_ship_grid(wfiles[p1_conn], boards[0])
    send_ship_grid(wfiles[p2_conn], boards[1])
    send(wfiles[p1_conn], "[INFO] You are Player 1.")
    send(wfiles[p2_conn], "[INFO] You are Player 2.")

    turn_idx = 0  # 0 ⇒ Player 1’s turn, 1 ⇒ Player 2’s turn
    while True:
        attacker = conns[turn_idx]
        defender = conns[1 - turn_idx]

        # prompt attacker
        send(wfiles[attacker], f"[TURN] Your move, Player {turn_idx+1}.")

        # wait until we get a chat or an attack
        while True:
            ready, _, _ = select.select(conns, [], [])
            for sock in ready:
                line = rfiles[sock].readline()
                if not line:
                    # connection closed
                    return
                line = line.strip()

                # 1) CHAT from either side ⇒ forward to the *other* player, do NOT swap turn
                if line.startswith("[CHAT]"):
                    msg         = line[len("[CHAT]"):].strip()
                    sender_id   = conns.index(sock) + 1
                    chat_line   = f"[CHAT] Player {sender_id}: {msg}"
                    target_conn = defender if sock is attacker else attacker
                    send(wfiles[target_conn], chat_line)
                    # stay in this inner loop
                    continue

                # 2) Non-chat from attacker ⇒ process as shot
                if sock is attacker:
                    cmd = line[len("[CMD]"):].strip() if line.startswith("[CMD]") else line
                    try:
                        r, c = parse_coordinate(cmd)
                        result, sunk_name = boards[1 - turn_idx].fire_at(r, c)

                        # REPORT HIT / MISS
                        if result == 'hit':
                            hit_msg = f"HIT!{' You sank the ' + sunk_name + '!' if sunk_name else ''}"
                            send(wfiles[attacker], hit_msg)
                            send(wfiles[defender],
                                 f"[DEFENSE] Opponent hit your ship at {cmd}!")
                        elif result == 'miss':
                            send(wfiles[attacker], "MISS!")
                            send(wfiles[defender],
                                 f"[DEFENSE] Opponent missed at {cmd}.")
                        else:  # already_shot
                            send(wfiles[attacker], "Already fired there. Try again.")
                            # prompt attacker again without swapping
                            break

                        # UPDATE GRIDS
                        send_ship_grid(wfiles[defender], boards[1 - turn_idx])
                        send_board(wfiles[attacker], boards[1 - turn_idx])

                        # CHECK FOR WIN
                        if boards[1 - turn_idx].all_ships_sunk():
                            send(wfiles[attacker], " You WIN! Opponent's fleet destroyed.")
                            send(wfiles[defender], " You LOSE! All ships destroyed.")
                            return

                        # successful shot ⇒ swap turns
                        turn_idx = 1 - turn_idx

                    except Exception as e:
                        send(wfiles[attacker], f"Invalid input: {e}")

                    # break out of both loops to re-prompt next turn
                    break

                # 3) Non-chat from non-attacker ⇒ ignore or notify
                else:
                    send(wfiles[sock], "[INFO] Not your turn to attack. Use /chat to send messages.")
                    continue

            else:
                # no attack processed yet, remain in inner loop
                continue
            # attack was processed, exit inner loop
            break

def matchmaking_loop():
    print(f"[INFO] Server listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        while True:
            conn, addr = s.accept()
            print(f"[INFO] Client connected from {addr}")
            with lock:
                waiting_players.append(conn)
                if len(waiting_players) >= 2:
                    p1 = waiting_players.pop(0)
                    p2 = waiting_players.pop(0)
                    threading.Thread(target=handle_game, args=(p1, p2), daemon=True).start()

if __name__ == "__main__":
    matchmaking_loop()
