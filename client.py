import socket
import threading
import pygame
import sys

# Constants
HOST = '127.0.0.1'
PORT = 5000
BOARD_SIZE = 10
CELL_SIZE = 40
MARGIN = 20
GRID_GAP = 60
CHAT_WIDTH = 300
WINDOW_WIDTH = MARGIN * 3 + CELL_SIZE * BOARD_SIZE * 2 + GRID_GAP + CHAT_WIDTH + 20
WINDOW_HEIGHT = MARGIN * 4 + CELL_SIZE * BOARD_SIZE + 40

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (150, 150, 150)
BLUE = (30, 144, 255)
RED = (255, 69, 0)
GREEN = (34, 139, 34)
ORANGE = (255, 165, 0)
MAX_PLAYERS = 2
player1_board = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
player2_board = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]

own_board = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
enemy_board = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
last_result = ""
is_my_turn = False
running = True
input_mode = False
input_str = ""
message_history = []
MAX_HISTORY = 6
update_lock = threading.Lock()
needs_redraw = True
pending_update_coord = None
player_id = None


def parse_coord(coord_str):
    row = ord(coord_str[0].upper()) - ord('A')
    col = int(coord_str[1:]) - 1
    return row, col


def coord_to_str(row, col):
    return chr(ord('A') + row) + str(col + 1)


def draw_board(screen, font, boards=None):
    """
    If boards=[b1,b2], draws:
      | b1 (Player 1 own) | b2 (Player 2 own) | chat |
    Otherwise (player mode):
      | own_board | enemy_board | chat |
    """
    screen.fill(WHITE)

    # positions
    left_x = MARGIN
    mid_x  = MARGIN + BOARD_SIZE * CELL_SIZE + GRID_GAP
    chat_x = mid_x   + BOARD_SIZE * CELL_SIZE + GRID_GAP
    chat_y = MARGIN
    chat_h = MAX_HISTORY * 22 + 20

    # choose grids & titles
    if boards and len(boards) == 2:
        grids  = boards
        titles = ("Player 1", "Player 2")
    else:
        grids  = [own_board, enemy_board]
        titles = ("Your Board", "Enemy Board")

    # draw two side-by-side grids
    for (grid, title, x0) in zip(grids, titles, (left_x, mid_x)):
        # cells
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                rect = pygame.Rect(
                    x0 + c*CELL_SIZE,
                    MARGIN + r*CELL_SIZE,
                    CELL_SIZE, CELL_SIZE
                )
                pygame.draw.rect(screen, BLACK, rect, 2)
                sym = grid[r][c]
                if sym == 'S':
                    color = GREEN if title in ("Your Board","Player 1") else ORANGE
                    pygame.draw.rect(screen, color, rect.inflate(-6, -6))
                elif sym == 'X':
                    pygame.draw.rect(screen, RED, rect.inflate(-6, -6))
                elif sym.lower() == 'o':
                    pygame.draw.circle(screen, BLUE, rect.center, CELL_SIZE//6)

        # labels A–J and 1–10
        for i in range(BOARD_SIZE):
            screen.blit(font.render(chr(ord('A')+i), True, BLACK),
                        (x0 - 20, MARGIN + i*CELL_SIZE + 5))
            screen.blit(font.render(str(i+1), True, BLACK),
                        (x0 + i*CELL_SIZE + 5, MARGIN - 20))

        # title
        screen.blit(font.render(title, True, BLACK),
                    (x0, MARGIN + BOARD_SIZE*CELL_SIZE + 5))

    # chatbox on the far right
    pygame.draw.rect(screen, (240,240,240),
                     (chat_x, chat_y, CHAT_WIDTH, chat_h))
    pygame.draw.rect(screen, BLACK,
                     (chat_x, chat_y, CHAT_WIDTH, chat_h), 2)
    for i, msg in enumerate(message_history[-MAX_HISTORY:]):
        screen.blit(font.render(msg, True, BLACK),
                    (chat_x + 8, chat_y + 10 + i*22))

    # input mode line
    if input_mode:
        screen.blit(font.render("Command: " + input_str, True, BLACK),
                    (chat_x, chat_y + chat_h + 10))

    pygame.display.flip()

def receive_messages(rfile):
    global is_my_turn, last_result, needs_redraw, pending_update_coord, player_id, running
    while running:
        line = rfile.readline()
        if not line:
            print("[INFO] Connection closed by server.")
            running = False
            break
        line = line.strip()
        # handle server exit signal
        if line.startswith("[EXIT]"):
            print("[INFO] Server requested shutdown.")
            running = False
            break
        updated = False
        if line.startswith("[CHAT]"):
            message_history.append(line)
            needs_redraw = True
            print(line)
            if len(message_history) > MAX_HISTORY:
                message_history.pop(0)
            updated = True
        elif line.startswith("[DEFENSE]"):
            print(f"[DEFENSE] {line}")
            for word in reversed(line.split()):
                if len(word) >= 2 and word[0].isalpha() and word[1:].isdigit():
                    r, c = parse_coord(word.strip("!. "))
                    own_board[r][c] = 'X' if "hit" in line or "sank" in line else 'o'
                    updated = True
                    break
        elif line.startswith("HIT") or line.startswith("MISS") or "sank" in line:
            last_result = line
            print(f"[RESULT] {line}")
            if pending_update_coord:
                r, c = pending_update_coord
                enemy_board[r][c] = 'X' if "hit" in line or "sank" in line else 'o'
                pending_update_coord = None
            updated = True
        elif line.startswith("[TURN]"):
            is_my_turn = True
            print("[INFO] It's your turn.")
            updated = True
        elif line.startswith("GRID"):
            rfile.readline()
            for r in range(BOARD_SIZE):
                row = rfile.readline().split()[1:]
                enemy_board[r] = row
            rfile.readline()
            updated = True
        elif line.startswith("[SHIPS]"):
            player_line = rfile.readline().strip()
            if player_line == "Player 1":
                target_board = player1_board
            elif player_line == "Player 2":
                target_board = player2_board
            else:
                target_board = own_board  # fallback (for player mode)
                target_board[0] = player_line.strip().split()  # this line is actually a board row

            start_row = 1 if target_board is own_board else 0
            for r in range(start_row, BOARD_SIZE):
                row = rfile.readline().strip().split()
                target_board[r] = row
            rfile.readline()  # skip blank
            updated = True

        elif line.startswith("[INFO] You are Player"):
            try:
                player_id = int(line.split()[-1].rstrip('.'))
            except:
                pass
            print(line)
            message_history.append(line)
            if len(message_history) > MAX_HISTORY:
                message_history.pop(0)
            updated = True

        elif line.startswith("[INFO] Game over"):
            print(f"[GAME] {line}")
            message_history.append(line)
            if len(message_history) > MAX_HISTORY:
                message_history.pop(0)
            updated = True
        elif "WIN" in line or "LOSE" in line:
            last_result = line
            print(f"[GAME] {line}")
            is_my_turn = False
            updated = True
        else:
            message_history.append(line)
            print(line)
            if len(message_history) > MAX_HISTORY:
                message_history.pop(0)
        if updated:
            with update_lock:
                needs_redraw = True






def main():
    global is_my_turn, running, needs_redraw, pending_update_coord, input_mode, input_str
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption('Battleship - BEER Edition')
    font = pygame.font.SysFont(None, 28)
    with socket.socket() as s:
        s.connect((HOST, PORT))
        rfile, wfile = s.makefile('r'), s.makefile('w')
            # —— read the server’s count header ——
        hdr = rfile.readline().strip()
        if hdr.startswith("[COUNT]"):
            num, _, maxp = hdr.partition("] ")[2].partition("/")
            current = int(num)
            maxp    = int(maxp)
            print(f"[INFO] Players: {current}/{maxp}")
        else:
        # fallback
            current, maxp = 0, MAX_PLAYERS

        # if we’re already full, force spectator mode
        if current >= maxp:
            role = '/spectator'
            print("[WARN] Player slots full → joining as spectator.")
        else:
            role = input("Enter /player to play or /spectator to watch: ").strip().lower()

        wfile.write(role + "\n")
        wfile.flush()

        # read the server’s immediate response
        reply = rfile.readline().strip()
        print(reply)
        # if it’s an error, bail out before placement/game-loop
        if reply.startswith("[ERROR]") and role == '/player':
            print("[INFO] Exiting client because player slots are full.")
            return

        is_spectator = (role == '/spectator')

        if is_spectator:
            print("[INFO] You are now a spectator. Sit back and enjoy!")
            threading.Thread(target=receive_messages, args=(rfile,), daemon=True).start()
            clock = pygame.time.Clock()

            # Spectator view: left = P1 own_board, center = P2 own_board, right = chatbox
            while running:
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        running = False
                    elif ev.type == pygame.KEYDOWN:
                        if not input_mode and ev.key == pygame.K_t:
                            input_mode = True
                            input_str = ''
                            needs_redraw = True
                        elif input_mode:
                            if ev.key == pygame.K_ESCAPE:
                                input_mode = False
                                needs_redraw = True
                            elif ev.key == pygame.K_BACKSPACE:
                                input_str = input_str[:-1]
                                needs_redraw = True
                            elif ev.key == pygame.K_RETURN:
                                cmd = input_str.strip()
                                if cmd.lower().startswith('/chat '):
                                    message = cmd[6:].strip()
                                    print(f"[YOU] {message}")
                                    wfile.write(f"[CHAT]{message}\n"); wfile.flush()
                                    if len(message_history) > MAX_HISTORY:
                                        message_history.pop(0)
                                    needs_redraw = True
                                elif cmd.lower() == '/quit':
                                    wfile.write("quit\n"); wfile.flush()
                                    running = False
                                input_mode = False
                                input_str = ''
                                needs_redraw = True
                            elif ev.unicode and ev.unicode.isprintable():
                                input_str += ev.unicode
                                needs_redraw = True

                draw_board(screen, font, boards=[player1_board, player2_board])
                clock.tick(30)



        # Ship placement phase
        from battleship import Board, SHIPS
        board = Board()
        print("[INFO] Ship placement: '/random' for auto, '/manual' for step-by-step, '/start' to begin")
        placement_done = False
        while not placement_done:
            cmd = input('Placement> ').strip().lower()
            if cmd == '/random':
                max_attempts = 5
                attempt = 0
                while attempt < max_attempts:
                    board.place_ships_randomly()
                    if len(board.placed_ships) == len(SHIPS):
                        # Mirror to own_board for display
                        for r in range(BOARD_SIZE):
                            own_board[r] = list(board.hidden_grid[r])
                        print('[INFO] Ships randomly placed:')
                        for row in own_board:
                            print(' '.join(row))
                        break
                    else:
                        attempt += 1
                        print(f"[WARN] Random placement failed ({attempt}/{max_attempts}). Retrying...")
                
                if attempt == max_attempts:
                    print("[ERROR] Could not place all ships after multiple attempts. Try manual placement or restart.")
            elif cmd == '/manual':
                board.place_ships_manually()
                for r in range(BOARD_SIZE):
                    own_board[r] = list(board.hidden_grid[r])
                print('[INFO] Ships manually placed:')
                for row in own_board:
                    print(' '.join(row))
            elif cmd.lower().startswith('/place'):
                parts = cmd.split()
                if len(parts) != 4:
                    print("[ERROR] Usage: /place <coord> <H|V> <ship>")
                    continue
                _, coord_str, ori_str, ship_name = parts
                ori = ori_str.upper()
                if ori not in ('H', 'V'):
                    print("[ERROR] Orientation must be H or V.")
                    continue
                try:
                    row, col = parse_coord(coord_str)
                except ValueError as e:
                    print(f"[ERROR] Invalid coordinate: {e}")
                    continue

                # Find the ship size by case-insensitive match
                for name, size in SHIPS:
                    if name.lower() == ship_name.lower():
                        ship_display = name
                        ship_size = size
                        break
                else:
                    valid_names = [n for n, _ in SHIPS]
                    print(f"[ERROR] Unknown ship '{ship_name}'. Valid: {valid_names}")
                    continue

                orient_flag = 0 if ori == 'H' else 1
                # Validate placement
                if not board.can_place_ship(row, col, ship_size, orient_flag):
                    print(f"[ERROR] Cannot place {ship_display} at {coord_str} ({ori}).")
                    continue

                # Perform placement
                occupied = board.do_place_ship(row, col, ship_size, orient_flag)
                board.placed_ships.append({
                    'name': ship_display,
                    'positions': occupied
                })
                # Mirror to own_board for display
                for (r, c) in occupied:
                    own_board[r][c] = 'S'
                print(f"[INFO] Placed {ship_display} at {coord_str} ({ori}).")
     
            elif cmd == '/start':
                if len(board.placed_ships) == len(SHIPS):
                    placement_done = True
                else:
                    print(f"[ERROR] Not all ships placed ({len(board.placed_ships)}/{len(SHIPS)}). Complete placement before starting.")
            else:
                print("[ERROR] Unknown command. Use '/random', '/manual', or '/start'.")

        # send placement to server
        for row in own_board:
            wfile.write(' '.join(row) + '\n')
        wfile.flush()
        threading.Thread(target=receive_messages, args=(rfile,), daemon=True).start()
        clock = pygame.time.Clock()
        while running:
            with update_lock:
                if needs_redraw:
                    draw_board(screen, font)
                    needs_redraw = False
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if not input_mode and ev.key == pygame.K_t:
                        input_mode = True
                        input_str = ''
                        needs_redraw = True
                    elif input_mode:
                        if ev.key == pygame.K_ESCAPE:
                            input_mode = False
                            needs_redraw = True
                        elif ev.key == pygame.K_BACKSPACE:
                            input_str = input_str[:-1]
                            needs_redraw = True
                        elif ev.key == pygame.K_RETURN:
                            cmd = input_str.strip()
                            # quit command
                            if cmd.lower() == '/quit':
                                print("[INFO] Sending quit to server and exiting...")
                                wfile.write('quit\n'); wfile.flush()
                                running = False
                            # chat command
                            elif cmd.lower().startswith('/chat '):
                                message = cmd[6:].strip()
                                print(f"[YOU] {message}")
                                wfile.write(f"[CHAT]{message}\n"); wfile.flush()
                                # message_history.append(f"[CHAT] Player {player_id}: {message}")
                                if len(message_history) > MAX_HISTORY:
                                    message_history.pop(0)
                                needs_redraw = True
                            # attack command
                            elif is_my_turn:
                                try:
                                    r, c = parse_coord(cmd)
                                    print(f"[ATTACK] {cmd.upper()}")
                                    pending_update_coord = (r, c)
                                    wfile.write(f"{cmd.upper()}\n"); wfile.flush()
                                    is_my_turn = False
                                except:
                                    print("[ERROR] Invalid coordinate")
                            input_mode = False
                            input_str = ''
                            needs_redraw = True
                        elif ev.unicode and ev.unicode.isprintable():
                            input_str += ev.unicode
                            needs_redraw = True
                elif ev.type == pygame.MOUSEBUTTONDOWN and not input_mode and is_my_turn:
                    mx, my = pygame.mouse.get_pos()
                    ex = MARGIN + BOARD_SIZE * CELL_SIZE + GRID_GAP
                    if ex <= mx <= ex + BOARD_SIZE * CELL_SIZE and MARGIN <= my <= MARGIN + BOARD_SIZE * CELL_SIZE:
                        r = (my - MARGIN) // CELL_SIZE
                        c = (mx - ex) // CELL_SIZE
                        print(f"[ATTACK] {coord_to_str(r, c)}")
                        pending_update_coord = (r, c)
                        wfile.write(coord_to_str(r, c) + '\n'); wfile.flush()
                        is_my_turn = False
        clock.tick(30)
    print("[INFO] Exiting client.")
    pygame.quit()
    sys.exit()

if __name__ == '__main__':
    main()