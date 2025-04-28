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
WINDOW_HEIGHT = MARGIN * 4 + CELL_SIZE * BOARD_SIZE + 40  # extra space for UI

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (150, 150, 150)    # Input box background
BLUE = (30, 144, 255)     # Missed shot
RED = (255, 69, 0)        # Hit
GREEN = (34, 139, 34)     # Player's ship
ORANGE = (255, 165, 0)    # Enemy ship (only for display)

# Boards
own_board = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
enemy_board = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
last_result = ""
is_my_turn = False
running = True

# Input box state
input_mode = False
input_str = ""

# Thread-safe update trigger
update_lock = threading.Lock()
needs_redraw = True
pending_update_coord = None


def parse_coord(coord_str):
    row = ord(coord_str[0].upper()) - ord('A')
    col = int(coord_str[1:]) - 1
    return row, col


def coord_to_str(row, col):
    return chr(ord('A') + row) + str(col + 1)


def draw_board(screen, font):
    screen.fill(WHITE)

    # Draw boards
    for board_type in ['own', 'enemy']:
        board = own_board if board_type == 'own' else enemy_board
        x0 = MARGIN if board_type == 'own' else MARGIN + BOARD_SIZE * CELL_SIZE + GRID_GAP
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                rect = pygame.Rect(x0 + c * CELL_SIZE,
                                   MARGIN + r * CELL_SIZE,
                                   CELL_SIZE, CELL_SIZE)
                pygame.draw.rect(screen, BLACK, rect, 2)
                sym = board[r][c]
                if sym == 'S':
                    color = GREEN if board_type == 'own' else ORANGE
                    pygame.draw.rect(screen, color, rect.inflate(-6, -6))
                elif sym == 'X':
                    pygame.draw.rect(screen, RED, rect.inflate(-6, -6))
                elif sym == 'o':
                    pygame.draw.circle(screen, BLUE, rect.center, CELL_SIZE // 6)
        # Labels
        for i in range(BOARD_SIZE):
            screen.blit(font.render(chr(ord('A') + i), True, BLACK),
                        (x0 - 20, MARGIN + i * CELL_SIZE + 5))
            screen.blit(font.render(str(i + 1), True, BLACK),
                        (x0 + i * CELL_SIZE + 5, MARGIN - 20))
        # Title
        title = "Your Board" if board_type == 'own' else "Enemy Board"
        screen.blit(font.render(title, True, BLACK),
                    (x0, MARGIN + BOARD_SIZE * CELL_SIZE + 5))

    # Status
    status_text = "Your turn! Click or T to type." if is_my_turn else "Waiting for opponent..."
    screen.blit(font.render(status_text, True, BLACK), (MARGIN, WINDOW_HEIGHT - 80))
    if last_result:
        screen.blit(font.render(f"Last result: {last_result}", True, BLACK), (MARGIN, WINDOW_HEIGHT - 55))

    # Input box
    if input_mode:
        box_w = 160 + len(input_str) * 12
        box_h = font.get_height() + 8
        box_x, box_y = MARGIN, WINDOW_HEIGHT - 40
        pygame.draw.rect(screen, GRAY, (box_x, box_y, box_w, box_h))
        pygame.draw.rect(screen, BLACK, (box_x, box_y, box_w, box_h), 2)
        # Show prompt and text
        prompt = font.render('Type: ' + input_str, True, BLACK)
        screen.blit(prompt, (box_x + 4, box_y + 4))

    pygame.display.flip()


def receive_messages(rfile):
    global is_my_turn, last_result, needs_redraw, pending_update_coord
    while running:
        line = rfile.readline()
        if not line:
            break
        line = line.strip()
        updated = False
        if line.startswith("[DEFENSE]"):
            for word in reversed(line.split()):
                if len(word) >= 2 and word[0].isalpha() and word[1:].isdigit():
                    r,c = parse_coord(word.strip("!. "))
                    own_board[r][c] = 'X' if "hit" in line or "sank" in line else 'o'
                    updated = True
                    break
        elif line.startswith("HIT") or line.startswith("MISS") or "sank" in line:
            last_result = line
            if pending_update_coord:
                r,c = pending_update_coord
                enemy_board[r][c] = 'X' if "hit" in line or "sank" in line else 'o'
                pending_update_coord = None
            updated = True
        elif line.startswith("[TURN]"):
            is_my_turn = True; updated = True
        elif line.startswith("GRID"):
            rfile.readline()
            for r in range(BOARD_SIZE):
                row = rfile.readline().split()[1:]
                enemy_board[r] = row
            rfile.readline(); updated = True
        elif line.startswith("[SHIPS]"):
            for r in range(BOARD_SIZE):
                own_board[r] = rfile.readline().split()
            rfile.readline(); updated = True
        elif "WIN" in line or "LOSE" in line:
            last_result = line; is_my_turn = False; updated = True
        else:
            print(line)
        if updated:
            with update_lock:
                needs_redraw = True


def main():
    global is_my_turn,running,needs_redraw,pending_update_coord,input_mode,input_str
    pygame.init()
    screen=pygame.display.set_mode((WINDOW_WIDTH,WINDOW_HEIGHT))
    pygame.display.set_caption('Battleship - BEER Edition')    
    font=pygame.font.SysFont(None,28)
    with socket.socket() as s:
        s.connect((HOST,PORT))
        rfile,wfile=s.makefile('r'),s.makefile('w')
        threading.Thread(target=receive_messages,args=(rfile,),daemon=True).start()
        clock=pygame.time.Clock()
        while running:
            with update_lock:
                if needs_redraw:
                    draw_board(screen,font); needs_redraw=False
            for ev in pygame.event.get():
                if ev.type==pygame.QUIT:
                    running=False
                elif ev.type==pygame.KEYDOWN:
                    if not input_mode and ev.key==pygame.K_t:
                        input_mode=True; input_str=''; needs_redraw=True
                    elif input_mode:
                        if ev.key==pygame.K_ESCAPE:
                            input_mode=False; needs_redraw=True
                        elif ev.key==pygame.K_BACKSPACE:
                            input_str=input_str[:-1]; needs_redraw=True
                        elif ev.key==pygame.K_RETURN and is_my_turn:
                            # send fire
                            cmd=input_str.upper()
                            try:
                                r,c=parse_coord(cmd)
                                pending_update_coord=(r,c)
                                wfile.write(cmd+'\n'); wfile.flush(); is_my_turn=False
                            except:
                                print(Exception)
                            input_mode=False; input_str=''; needs_redraw=True
                        elif ev.unicode.isalnum():
                            input_str+=ev.unicode; needs_redraw=True
                elif ev.type==pygame.MOUSEBUTTONDOWN and not input_mode and is_my_turn:
                    mx,my=pygame.mouse.get_pos(); ex=MARGIN+BOARD_SIZE*CELL_SIZE+GRID_GAP
                    if ex<=mx<=ex+BOARD_SIZE*CELL_SIZE and MARGIN<=my<=MARGIN+BOARD_SIZE*CELL_SIZE:
                        r=(my-MARGIN)//CELL_SIZE; c=(mx-ex)//CELL_SIZE
                        pending_update_coord=(r,c)
                        wfile.write(coord_to_str(r,c)+'\n'); wfile.flush(); is_my_turn=False
            clock.tick(30)
    pygame.quit()

if __name__ == '__main__':
    main()