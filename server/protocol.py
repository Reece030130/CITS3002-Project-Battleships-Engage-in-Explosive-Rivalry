from typing import TextIO

def send(wfile: TextIO, msg: str) -> None:
    """Send a single-line message to the client."""
    wfile.write(msg + "\n")
    wfile.flush()


def send_board(wfile: TextIO, board) -> None:
    """Send the opponent's visible grid to the attacker."""
    wfile.write("GRID\n")
    wfile.write("  " + " ".join(str(i + 1).rjust(2) for i in range(board.size)) + "\n")
    for r in range(board.size):
        row_label = chr(ord('A') + r)
        row_str   = " ".join(board.display_grid[r][c] for c in range(board.size))
        wfile.write(f"{row_label:2} {row_str}\n")
    wfile.write("\n")
    wfile.flush()


def send_ship_grid(wfile: TextIO, board) -> None:
    """Send the defender's hidden grid (their ship layout)."""
    wfile.write("[SHIPS]\n")
    for r in range(board.size):
        wfile.write(" ".join(board.hidden_grid[r]) + "\n")
    wfile.write("\n")
    wfile.flush()