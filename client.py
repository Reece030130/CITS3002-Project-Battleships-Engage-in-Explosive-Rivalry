import socket
import threading
import pygame

# Constants
HOST = '127.0.0.1'
PORT = 5000
BOARD_SIZE = 10
CELL_SIZE = 40
MARGIN = 20
GRID_GAP = 60  # Gap between own and enemy boards
WINDOW_WIDTH = MARGIN * 3 + CELL_SIZE * BOARD_SIZE * 2 + GRID_GAP
WINDOW_HEIGHT = MARGIN * 2 + CELL_SIZE * BOARD_SIZE + 100

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (180, 180, 180)
BLUE = (30, 144, 255)    # Missed shot
RED = (255, 69, 0)       # Hit
GREEN = (34, 139, 34)    # Player's ship
ORANGE = (255, 165, 0)   # Enemy ship (only for display)

# Boards
own_board = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
enemy_board = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
last_result = ""
is_my_turn = False
running = True

# Thread-safe update trigger
update_lock = threading.Lock()
needs_redraw = True

pending_update_coord = None  # Coordinate to manually update after fire


def parse_coord(coord_str):
    row = ord(coord_str[0].upper()) - ord('A')
    col = int(coord_str[1:]) - 1
    return row, col


def coord_to_str(row, col):
    return chr(ord('A') + row) + str(col + 1)


def draw_board(screen, font):
    screen.fill(WHITE)

    for board_type in ['own', 'enemy']:
        board = own_board if board_type == 'own' else enemy_board
        x_offset = MARGIN if board_type == 'own' else MARGIN + BOARD_SIZE * CELL_SIZE + GRID_GAP

        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                rect = pygame.Rect(x_offset + col * CELL_SIZE,
                                   MARGIN + row * CELL_SIZE,
                                   CELL_SIZE, CELL_SIZE)
                pygame.draw.rect(screen, BLACK, rect, 2)

                symbol = board[row][col]
                if symbol == 'S':
                    color = GREEN if board_type == 'own' else ORANGE
                    pygame.draw.rect(screen, color, rect.inflate(-6, -6))
                elif symbol == 'X':
                    pygame.draw.line(screen, RED, rect.topleft, rect.bottomright, 3)
                    pygame.draw.line(screen, RED, rect.topright, rect.bottomleft, 3)
                elif symbol == 'o':
                    pygame.draw.circle(screen, BLUE, rect.center, CELL_SIZE // 6)

        for i in range(BOARD_SIZE):
            label = font.render(chr(ord('A') + i), True, BLACK)
            screen.blit(label, (x_offset - 20, MARGIN + i * CELL_SIZE + CELL_SIZE // 3))
            label = font.render(str(i + 1), True, BLACK)
            screen.blit(label, (x_offset + i * CELL_SIZE + CELL_SIZE // 3, MARGIN - 20))

        label = font.render("Your Board" if board_type == 'own' else "Enemy Board", True, BLACK)
        screen.blit(label, (x_offset, MARGIN + BOARD_SIZE * CELL_SIZE + 10))

    status = "Your turn! Click a cell on enemy board." if is_my_turn else "Waiting for opponent..."
    status_surface = font.render(status, True, BLACK)
    screen.blit(status_surface, (MARGIN, WINDOW_HEIGHT - 60))

    if last_result:
        result_surface = font.render(f"Last result: {last_result}", True, BLACK)
        screen.blit(result_surface, (MARGIN, WINDOW_HEIGHT - 30))

    pygame.display.flip()


def receive_messages(rfile):
    global is_my_turn, last_result, needs_redraw, pending_update_coord
    while running:
        line = rfile.readline()
        if not line:
            print("[INFO] Server disconnected.")
            break

        line = line.strip()
        updated = False

        if line.startswith("[DEFENSE]"):
            words = line.split()
            for word in reversed(words):
                if len(word) >= 2 and word[0].isalpha() and word[1:].isdigit():
                    coord = word.strip("!. ").upper()
                    try:
                        row, col = parse_coord(coord)
                        if "hit" in line or "sank" in line:
                            own_board[row][col] = 'X'
                        elif "missed" in line:
                            own_board[row][col] = 'o'
                        updated = True
                    except:
                        pass
                    break

        elif line.startswith("HIT") or line.startswith("MISS") or "sank" in line:
            last_result = line
            if pending_update_coord:
                row, col = pending_update_coord
                if "hit" in line or "sank" in line:
                    enemy_board[row][col] = 'X'
                elif "MISS" in line:
                    enemy_board[row][col] = 'o'
                pending_update_coord = None
            updated = True

        elif line.startswith("[TURN]"):
            is_my_turn = True
            updated = True

        elif line.startswith("GRID"):
            rfile.readline()
            for r in range(BOARD_SIZE):
                row_data = rfile.readline().strip().split()
                enemy_board[r] = row_data[1:]
            rfile.readline()
            updated = True

        elif line.startswith("[SHIPS]"):
            for r in range(BOARD_SIZE):
                row_data = rfile.readline().strip().split()
                own_board[r] = row_data
            rfile.readline()
            updated = True

        elif "WIN" in line or "LOSE" in line:
            last_result = line
            is_my_turn = False
            updated = True

        else:
            print(line)

        if updated:
            with update_lock:
                needs_redraw = True


def main():
    global is_my_turn, running, needs_redraw, pending_update_coord
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Battleship - BEER Edition")
    font = pygame.font.SysFont(None, 28)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        rfile = s.makefile('r')
        wfile = s.makefile('w')

        threading.Thread(target=receive_messages, args=(rfile,), daemon=True).start()

        clock = pygame.time.Clock()

        while running:
            with update_lock:
                if needs_redraw:
                    draw_board(screen, font)
                    needs_redraw = False

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.MOUSEBUTTONDOWN and is_my_turn:
                    mx, my = pygame.mouse.get_pos()
                    ex = MARGIN + BOARD_SIZE * CELL_SIZE + GRID_GAP
                    if ex <= mx <= ex + BOARD_SIZE * CELL_SIZE and MARGIN <= my <= MARGIN + BOARD_SIZE * CELL_SIZE:
                        col = (mx - ex) // CELL_SIZE
                        row = (my - MARGIN) // CELL_SIZE
                        coord_str = coord_to_str(row, col)
                        pending_update_coord = (row, col)
                        wfile.write(coord_str + '\n')
                        wfile.flush()
                        is_my_turn = False

            clock.tick(30)

    pygame.quit()


if __name__ == '__main__':
    main()
