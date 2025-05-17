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
        self.conns = [p1_conn, p2_conn]
        self.rfiles = {c: c.makefile('r') for c in self.conns}
        self.wfiles = {c: c.makefile('w') for c in self.conns}
        self.spectators = []
        self.boards = []
        self.chat_history: list[str] = []

    def add_spectator(self, conn):
        
            self.spectators.append(conn)

            self.rfiles[conn] = conn.makefile('r')
            self.wfiles[conn] = conn.makefile('w')
            wf = self.wfiles[conn]

            protocol.send(wf, "[INFO] You are now spectating.")

            for past_msg in self.chat_history:
                protocol.send(wf, past_msg)

            if self.boards:
                for idx, board in enumerate(self.boards):
                    protocol.send_ship_grid(wf, board, player_id=idx+1)

    def run(self):
        self.handle_game()

    def placement_phase(self) -> list[Board]:
        boards = [Board(), Board()]
        for idx, conn in enumerate(self.conns):
            protocol.send(self.wfiles[conn], "[REQUEST_PLACEMENT]")

            rows = []
            while len(rows) < BOARD_SIZE:
                line = self.rfiles[conn].readline()
                if not line:
                    raise ConnectionError("Client disconnected during placement")
                parts = line.strip().split()
                if len(parts) != BOARD_SIZE:
                    continue
                if any(ch not in (".", "S") for ch in parts):
                    raise ValueError(f"Bad placement row: {parts}")
                rows.append(parts)

            temp = []
            for r, row in enumerate(rows):
                boards[idx].hidden_grid[r] = row
                temp.append(row.copy())

            boards[idx].placed_ships = []
            try_count = 0
            while try_count < 3:
                success = True
                ship_tracker = [row.copy() for row in temp]
                boards[idx].placed_ships = []

                for ship_name, ship_size in SHIPS:
                    placed = False
                    for i in range(BOARD_SIZE):
                        for j in range(BOARD_SIZE):
                            if j + ship_size <= BOARD_SIZE and all(ship_tracker[i][j+k] == 'S' for k in range(ship_size)):
                                pos = {(i, j+k) for k in range(ship_size)}
                                boards[idx].placed_ships.append({'name': ship_name, 'positions': pos})
                                for (rr, cc) in pos:
                                    ship_tracker[rr][cc] = '.'
                                placed = True
                                break
                            if i + ship_size <= BOARD_SIZE and all(ship_tracker[i+k][j] == 'S' for k in range(ship_size)):
                                pos = {(i+k, j) for k in range(ship_size)}
                                boards[idx].placed_ships.append({'name': ship_name, 'positions': pos})
                                for (rr, cc) in pos:
                                    ship_tracker[rr][cc] = '.'
                                placed = True
                                break
                        if placed:
                            break
                    if not placed:
                        success = False
                        try_count += 1
                        print(f"[WARN] Failed to find ship: {ship_name} for Player {idx+1}, retrying...")
                        break

                if success:
                    break
            else:
                raise ValueError(f"Failed to reconstruct ship layout for Player {idx+1} after retries.")

        return boards

    def chat_only_phase(self):
    # 通知玩家游戏结束，可聊天或退出
        for c in self.conns:
            protocol.send(self.wfiles[c], "[INFO] Game over. You may /chat or type quit to exit.")
        while True:
            # 等待任意玩家或观战者发来输入
            ready, _, _ = select.select(self.conns + self.spectators, [], [])
            for sock in ready:
                line = self.rfiles[sock].readline()
                # 客户端断开或发 quit
                if not line or line.strip().lower() == 'quit':
                    if sock in self.conns:
                        other = self.conns[1 - self.conns.index(sock)]
                        protocol.send(self.wfiles[other], "[EXIT] Server shutting down.")
                    os._exit(0)

                line = line.strip()
                # 只有 “[CHAT]…” 的才做聊天广播
                if not line.startswith("[CHAT]"):
                    protocol.send(self.wfiles[sock], "[INFO] Game over: use /chat or quit to exit.")
                    continue

                # 提取消息体
                msg = line[len("[CHAT]"):].strip()

                # 区分玩家 / 观战者
                if sock in self.conns:
                    sid = self.conns.index(sock) + 1
                    formatted = f"[CHAT] Player {sid}: {msg}"
                    targets = self.conns + self.spectators
                else:  # sock in self.spectators
                    formatted = f"[CHAT] Spectator: {msg}"
                    targets = self.spectators

                # 缓存历史（可选，也方便新加入观战者补发）
                self.chat_history.append(formatted)
                if len(self.chat_history) > 100:
                    self.chat_history.pop(0)

                # 广播给对应对象
                for peer in targets:
                    protocol.send(self.wfiles[peer], formatted)


    def handle_game(self):
        # —— 1. 布舰阶段 —— 
        self.boards = self.placement_phase()

        # —— 2. 初始广播棋盘 & 身份 —— 
        for idx, conn in enumerate(self.conns):
            protocol.send_ship_grid(self.wfiles[conn], self.boards[idx], player_id=idx+1)
            protocol.send(self.wfiles[conn], f"[INFO] You are Player {idx+1}.")
        # 观战者也要看到双方棋盘
        for spec in self.spectators:
            for idx, board in enumerate(self.boards):
                protocol.send_ship_grid(self.wfiles[spec], board, player_id=idx+1)

        # —— 3. 回合循环 —— 
        turn_idx = 0
        while True:
            attacker = self.conns[turn_idx]
            defender = self.conns[1 - turn_idx]
            defender_board = self.boards[1 - turn_idx]

            # 通知行动者 & 观战者
            protocol.send(self.wfiles[attacker], f"[TURN] Your move, Player {turn_idx+1}.")
            for spec in self.spectators:
                protocol.send(self.wfiles[spec], f"[INFO] Player {turn_idx+1} to move.")

            # 等待射击或聊天
            while True:
                ready, _, _ = select.select(self.conns + self.spectators, [], [])
                for sock in ready:
                    raw = self.rfiles[sock].readline()
                    if not raw or raw.strip().lower() == 'quit':
                        if sock in self.conns:
                            other = self.conns[1 - self.conns.index(sock)]
                            protocol.send(self.wfiles[other], "[EXIT] Server shutting down.")
                        os._exit(0)

                    line = raw.strip()

                    # —— 聊天优先 —— 
                    if line.startswith("[CHAT]"):
                        msg = line[len("[CHAT]"):].strip()
                        if sock in self.conns:
                            sid = self.conns.index(sock) + 1
                            formatted = f"[CHAT] Player {sid}: {msg}"
                            targets = self.conns + self.spectators
                        else:
                            formatted = f"[CHAT] Spectator: {msg}"
                            targets = self.spectators

                        # 缓存并广播
                        self.chat_history.append(formatted)
                        if len(self.chat_history) > 100:
                            self.chat_history.pop(0)
                        for peer in targets:
                            protocol.send(self.wfiles[peer], formatted)
                        # 聊天处理完，继续等下一个输入
                        continue

                    # —— 射击逻辑，仅限当前行动者 —— 
                    if sock is not attacker:
                        # 其他人试操作就提示
                        protocol.send(self.wfiles[sock], "[INFO] Not your turn. Use /chat.")
                        continue

                    # 真正的射击请求
                    try:
                        r, c = parse_coordinate(line)
                        result, sunk = defender_board.fire_at(r, c)
                        if result == 'hit':
                            protocol.send(self.wfiles[attacker],
                                        f"HIT!{' You sank ' + sunk + '!' if sunk else ''}")
                            protocol.send(self.wfiles[defender],
                                        f"[DEFENSE] Opponent hit at {line}.")
                        elif result == 'miss':
                            protocol.send(self.wfiles[attacker], "MISS!")
                            protocol.send(self.wfiles[defender],
                                        f"[DEFENSE] Opponent missed at {line}.")
                        else:
                            protocol.send(self.wfiles[attacker], "Already fired there. Try again.")
                            break

                        # 更新并广播最新棋盘
                        protocol.send_ship_grid(self.wfiles[defender], defender_board)
                        protocol.send_board(self.wfiles[attacker], defender_board)
                        for spec in self.spectators:
                            for b_idx, b in enumerate(self.boards):
                                protocol.send_ship_grid(self.wfiles[spec], b, player_id=b_idx+1)

                        # 胜负判断
                        if result == 'hit' and defender_board.all_ships_sunk():
                            protocol.send(self.wfiles[attacker], "[END] You WIN! Fleet destroyed.")
                            protocol.send(self.wfiles[defender], "[END] You LOSE! Fleet destroyed.")
                            # 跳到仅聊天阶段
                            self.chat_only_phase()
                            return

                        # 切换回合
                        turn_idx = 1 - turn_idx

                    except Exception as e:
                        protocol.send(self.wfiles[attacker], f"Invalid input: {e}")
                    # 射击执行完毕，跳出 inner loop 进入下一回合
                    break
                else:
                    # 如果 inner while 没 break，则继续 select
                    continue
                break
