import socket, threading
from handle_game import GameSession
import protocol
from config import HOST, PORT, MAX_PLAYERS, MAX_SPECTATORS

waiting_players: list[socket.socket] = []
sessions: list[GameSession]  = []
lock = threading.Lock()

def matchmaking_loop() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((HOST, PORT))
        listener.listen()
        print(f"[INFO] Server listening on {HOST}:{PORT}")
        while True:
            conn, _ = listener.accept()
            rfile = conn.makefile('r')
            wfile = conn.makefile('w')
            # figure out how many players are already “in the pool” or in an ongoing session
            with lock:
                if sessions and sessions[-1].is_alive():
                    current_players = MAX_PLAYERS
                else:
                    current_players = len(waiting_players)

            # send a machine-readable count header
            protocol.send(wfile, f"[COUNT] {current_players}/{MAX_PLAYERS}")

            protocol.send(wfile, "[INFO] Enter /player to play or /spectator to watch.")
            choice = rfile.readline().strip().lower()

            with lock:
                # ─── Spectator ───────────────────────────────────────────
                if choice == '/spectator':
                    if not sessions:
                        protocol.send(wfile, "[ERROR] No game in progress. Try again later.")
                        conn.close()
                    else:
                        sess = sessions[-1]
                        if len(sess.spectators) >= MAX_SPECTATORS:
                            protocol.send(wfile, "[ERROR] Spectator limit reached.")
                            conn.close()
                        else:
                            sess.add_spectator(conn)

                # ─── Player ──────────────────────────────────────────────
                elif choice == '/player':
                    # are we already full?
                    if len(waiting_players) >= MAX_PLAYERS or \
                       (sessions and sessions[-1].is_alive()):
                        protocol.send(wfile, "[ERROR] Player slots are full. Try /spectator.")
                        conn.close()
                    else:
                        waiting_players.append(conn)
                        protocol.send(wfile, "[INFO] Waiting for another player…")

                        # once we have two, start immediately
                        if len(waiting_players) == MAX_PLAYERS:
                            p1 = waiting_players.pop(0)
                            p2 = waiting_players.pop(0)

                            session = GameSession(p1, p2)
                            session.start()
                            sessions.append(session)

                # ─── Invalid ────────────────────────────────────────────
                else:
                    protocol.send(wfile, "[ERROR] Invalid command.")
                    conn.close()

if __name__ == '__main__':
    matchmaking_loop()
