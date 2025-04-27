import socket
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
        row_str = " ".join(board.display_grid[r][c] for c in range(board.size))
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
    p1_r = p1_conn.makefile('r')
    p1_w = p1_conn.makefile('w')
    p2_r = p2_conn.makefile('r')
    p2_w = p2_conn.makefile('w')

    board1 = Board()
    board2 = Board()
    board1.place_ships_randomly()
    board2.place_ships_randomly()

    send_ship_grid(p1_w, board1)
    send_ship_grid(p2_w, board2)

    send(p1_w, "[INFO] You are Player 1.")
    send(p2_w, "[INFO] You are Player 2.")

    current_turn = 1
    while True:
        attacker_r, attacker_w = (p1_r, p1_w) if current_turn == 1 else (p2_r, p2_w)
        defender_board = board2 if current_turn == 1 else board1
        defender_w = p2_w if current_turn == 1 else p1_w

        send(attacker_w, f"[TURN] Your move, Player {current_turn}.")

        guess = attacker_r.readline().strip()
        if guess.lower() == 'quit':
            send(p1_w, "[INFO] Game ended. Opponent quit.")
            send(p2_w, "[INFO] Game ended. Opponent quit.")
            return

        try:
            row, col = parse_coordinate(guess)
            result, sunk_name = defender_board.fire_at(row, col)

            # Attacker gets feedback
            if result == 'hit':
                msg = f"HIT! You sank the {sunk_name}!" if sunk_name else "HIT!"
                send(attacker_w, msg)
                send(defender_w, f"[DEFENSE] Opponent hit your ship at {guess}!")
                if sunk_name:
                    send_ship_grid(defender_w, defender_board)
            elif result == 'miss':
                send(attacker_w, "MISS!")
                send(defender_w, f"[DEFENSE] Opponent missed at {guess}.")
            elif result == 'already_shot':
                send(attacker_w, "Already fired there. Try again.")
                continue

            # Piggyback: always send updated board to attacker
            send_board(attacker_w, defender_board)

            if defender_board.all_ships_sunk():
                send(attacker_w, "🎉 You WIN! Opponent's fleet destroyed.")
                send(defender_w, "💥 You LOSE! All ships destroyed.")
                return

            current_turn = 2 if current_turn == 1 else 1

        except Exception as e:
            send(attacker_w, f"Invalid input: {e}")


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