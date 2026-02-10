import chess

# 1. Create a new board
board = chess.Board()

# 2. Print a text version of the starting board
print("Starting Position:")
print(board)

# 3. Try a move (Scholar's Mate attempt)
moves = ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]

for m in moves:
    move = chess.Move.from_uci(m)
    if move in board.legal_moves:
        board.push(move)
        print(f"\nMove {m} was successful!")
        print(board)
    else:
        print(f"\nIllegal move attempted: {m}")

# 4. Check for Checkmate
if board.is_checkmate():
    print("\nGAME OVER: Checkmate!")