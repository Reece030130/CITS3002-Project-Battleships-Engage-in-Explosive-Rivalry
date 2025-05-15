import os
import select
import threading
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from battleship import Board, parse_coordinate, SHIPS, BOARD_SIZE
import protocol

class GameSession(threading.Thread):
    """Handles one match between two players."""
    def __init__(self, p1_conn, p2_conn):
        super().__init__(daemon=True)
        self.conns  = [p1_conn, p2_conn]
        self.rfiles = {c: c.makefile('r') for c in self.conns}
        self.wfiles = {c: c.makefile('w') for c in self.conns}

    def run(self) -> None:
        self.handle_game()

    def placement_phase(self) -> list[Board]:
            """Exchange ship-placement grids and reconstruct ship lists robustly."""
            boards = [Board(), Board()]
            for idx, conn in enumerate(self.conns):
                protocol.send(self.wfiles[conn], "[REQUEST_PLACEMENT]")

                # Read exactly BOARD_SIZE valid rows, skipping any stray lines
                rows = []
                while len(rows) < BOARD_SIZE:
                    line = self.rfiles[conn].readline()
                    if not line:
                        raise ConnectionError("Client disconnected during placement")
                    parts = line.strip().split()
                    # filter out empty or malformed lines
                    if len(parts) != BOARD_SIZE:
                        continue
                    if any(ch not in (".", "S") for ch in parts):
                        raise ValueError(f"Bad placement row: {parts}")
                    rows.append(parts)

                # populate hidden_grid and temp copy for reconstruction
                temp = []
                for r, row in enumerate(rows):
                    boards[idx].hidden_grid[r] = row
                    temp.append(row.copy())

                # reconstruct placed_ships from hidden_grid
                boards[idx].placed_ships = []
                for ship_name, ship_size in SHIPS:
                    placed = False
                    for i in range(BOARD_SIZE):
                        for j in range(BOARD_SIZE):
                            # horizontal
                            if j + ship_size <= BOARD_SIZE and all(temp[i][j+k] == 'S' for k in range(ship_size)):
                                pos = {(i, j+k) for k in range(ship_size)}
                                boards[idx].placed_ships.append({'name': ship_name, 'positions': pos})
                                for (rr, cc) in pos:
                                    temp[rr][cc] = '.'
                                placed = True
                                break
                            # vertical
                            if i + ship_size <= BOARD_SIZE and all(temp[i+k][j] == 'S' for k in range(ship_size)):
                                pos = {(i+k, j) for k in range(ship_size)}
                                boards[idx].placed_ships.append({'name': ship_name, 'positions': pos})
                                for (rr, cc) in pos:
                                    temp[rr][cc] = '.'
                                placed = True
                                break
                        if placed:
                            break
                    if not placed:
                        raise ValueError(f"Invalid placement: missing {ship_name}")
            return boards

    def chat_only_phase(self) -> None:
        """After game over, allow players to chat until quit."""
        for c in self.conns:
            protocol.send(self.wfiles[c], "[INFO] Game over. You may /chat or type quit to exit.")
        while True:
            ready, _, _ = select.select(self.conns, [], [])
            for sock in ready:
                line = self.rfiles[sock].readline()
                if not line or line.strip().lower() == 'quit':
                    other = self.conns[1 - self.conns.index(sock)]
                    protocol.send(self.wfiles[other], "[EXIT] Server shutting down.")
                    os._exit(0)
                line = line.strip()
                if line.startswith("[CHAT]"):
                    sid = self.conns.index(sock) + 1
                    msg = line[len("[CHAT]"):].strip()
                    other = self.conns[1 - self.conns.index(sock)]
                    protocol.send(self.wfiles[other], f"[CHAT] Player {sid}: {msg}")
                else:
                    protocol.send(self.wfiles[sock], "[INFO] Game over: use /chat or quit to exit.")

    def handle_game(self) -> None:
        # 1) Placement
        boards = self.placement_phase()
        # send back placements & IDs
        for idx, conn in enumerate(self.conns):
            protocol.send_ship_grid(self.wfiles[conn], boards[idx])
            protocol.send(self.wfiles[conn], f"[INFO] You are Player {idx+1}.")

        # 2) Main loop
        turn_idx = 0
        while True:
            attacker = self.conns[turn_idx]
            defender = self.conns[1 - turn_idx]
            defender_board = boards[1 - turn_idx]

            protocol.send(self.wfiles[attacker], f"[TURN] Your move, Player {turn_idx+1}.")

            while True:
                ready, _, _ = select.select(self.conns, [], [])
                for sock in ready:
                    raw = self.rfiles[sock].readline()
                    if not raw or raw.strip().lower() == 'quit':
                        other = self.conns[1 - self.conns.index(sock)]
                        protocol.send(self.wfiles[other], "[EXIT] Server shutting down.")
                        os._exit(0)
                    line = raw.strip()
                    # chat
                    if line.startswith("[CHAT]"):
                        sid = self.conns.index(sock) + 1
                        msg = line[len("[CHAT]"):].strip()
                        target = defender if sock is attacker else attacker
                        protocol.send(self.wfiles[target], f"[CHAT] Player {sid}: {msg}")
                        continue
                    # attack
                    if sock is attacker:
                        try:
                            r, c = parse_coordinate(line)
                            result, sunk = defender_board.fire_at(r, c)
                            if result == 'hit':
                                protocol.send(self.wfiles[attacker], f"HIT!{' You sank '+sunk+'!' if sunk else ''}")
                                protocol.send(self.wfiles[defender], f"[DEFENSE] Opponent hit at {line}.")
                            elif result == 'miss':
                                protocol.send(self.wfiles[attacker], "MISS!")
                                protocol.send(self.wfiles[defender], f"[DEFENSE] Opponent missed at {line}.")
                            else:
                                protocol.send(self.wfiles[attacker], "Already fired there. Try again.")
                                break
                            # update views
                            protocol.send_ship_grid(self.wfiles[defender], boards[1 - turn_idx])
                            protocol.send_board(self.wfiles[attacker], boards[1 - turn_idx])
                            # win?
                            if result == 'hit' and defender_board.all_ships_sunk():
                                protocol.send(self.wfiles[attacker], "[END] You WIN! Fleet destroyed.")
                                protocol.send(self.wfiles[defender], "[END] You LOSE! Fleet destroyed.")
                                self.chat_only_phase()
                                return
                            turn_idx = 1 - turn_idx
                        except Exception as e:
                            protocol.send(self.wfiles[attacker], f"Invalid input: {e}")
                        break
                    else:
                        protocol.send(self.wfiles[sock], "[INFO] Not your turn. Use /chat.")
                        continue
                else:
                    continue
                break