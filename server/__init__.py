import socket
import threading
from handle_game import GameSession

HOST = '127.0.0.1'
PORT = 5000

waiting_players = []
lock = threading.Lock()

def matchmaking_loop() -> None:
    """Accept new connections and pair into GameSession threads."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((HOST, PORT))
        listener.listen()
        print(f"[INFO] Server listening on {HOST}:{PORT}")
        while True:
            conn, _ = listener.accept()
            with lock:
                waiting_players.append(conn)
                if len(waiting_players) >= 2:
                    p1 = waiting_players.pop(0)
                    p2 = waiting_players.pop(0)
                    session = GameSession(p1, p2)
                    session.start()

if __name__ == '__main__':
    matchmaking_loop()