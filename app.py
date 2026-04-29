import io
import os
import sys
from flask import Flask, render_template, request, jsonify
import chess
import chess.engine
import chess.pgn
from dotenv import load_dotenv
from openai import OpenAI
import random

# --- THE FIX ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Point load_dotenv to the internal bundled file
load_dotenv(dotenv_path=resource_path(".env"))

# Tell Flask where to find your bundled HTML and CSS
app = Flask(__name__, 
            template_folder=resource_path('templates'), 
            static_folder=resource_path('static'))

# --- REST OF YOUR CODE ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DEFAULT_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1")

# When you eventually call Stockfish, remember to wrap it too:
# engine = chess.engine.SimpleEngine.popen_uci(resource_path("engines/stockfish.exe"))

system_instruction = (
    """
    You are a practical, concise, and accurate chess coach.
    Your job is to explain a single move using only the provided board data.
    Use exact piece names, exact squares, and exact move notation from the DATA.
    Never invent pieces, squares, tactics, threats, or move sequences not present in the current board data.
    If the data does not say it, do not claim it.

    CRITICAL RULES:
    1. Use the provided DATA literally. Only describe the move using the pieces and squares shown.
    2. If the move is categorized as Mistake, Blunder, or Missing Checkmate, identify the exact opponent piece and exact response move from the provided 'Engine's Best Next Move' data.
    3. Do not mention engine evaluations, centipawns, or speculative alternative moves.
    4. Answer in 1 to 4 sentences. No bullet lists. No headers. No fluff.

    CATEGORICAL RESPONSE GUIDELINES:
    - Opening/Book Move: Explain how the move develops a piece, controls center, or frees another piece.
    - Good/Positional Move: Explain the job the piece is doing, what it strengthens, or what square it controls.
    - Inaccuracy: Explain the small loss of tempo or why the opponent gets an easier path; do not label it a blunder.
    - Mistake: Explain the concrete problem the move creates or ignores.
    - Blunder: Identify what is hanging and what exact opponent response punishes it.
    - Missing Checkmate: Explain the fatal oversight and how the provided engine response finishes the win.
    - Missed Win: State the exact missed move from the data and what that move would have achieved.
    """
)

board = chess.Board()

@app.route('/')
def index():
    return render_template('index.html')

def get_engine_path():
    engine_name = "stockfish.exe" if os.name == "nt" else "stockfish"
    candidate = resource_path(os.path.join("engines", engine_name))
    if not os.path.exists(candidate):
        candidate = resource_path(os.path.join("engines", "stockfish"))
    return candidate

engine_path = get_engine_path()

def get_evaluation(fen):
    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        temp_board = chess.Board(fen)
        info = engine.analyse(temp_board, chess.engine.Limit(time=0.1))
        score = info["score"].white()
        if score.is_mate():
            mate_val = score.mate()
            return f"M{mate_val}" if mate_val is not None else "M"
        val = score.score()
        return val / 100.0 if val is not None else 0.0

@app.route('/move', methods=['POST'])
def make_move():
    global board
    data = request.json
    move_text = data.get("move")
    fen = data.get("fen")

    try:
        if fen:
            temp_board = chess.Board(fen)
        else:
            temp_board = chess.Board(board.fen())

        move = chess.Move.from_uci(move_text)
        if move in temp_board.legal_moves:
            temp_board.push(move)
            board = temp_board
            current_eval = get_evaluation(board.fen())
            return jsonify({
                "status": "success",
                "fen": board.fen(),
                "check": board.is_check(),
                "turn": "white" if board.turn == chess.WHITE else "black",
                "evaluation": current_eval
            })
        else:
            return jsonify({"status": "invalid", "message": "That move is against the rules!"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/reset', methods=['POST'])
def reset_board():
    global board
    board = chess.Board()
    return jsonify({"status": "reset", "board": board.fen()})

@app.route("/engine_move", methods=["POST"])
def engine_move():
    global board
    data = request.json
    fen = data.get("fen")
    if fen:
        temp_board = chess.Board(fen)
    else:
        temp_board = chess.Board(board.fen())

    if temp_board.is_game_over():
        return jsonify({"game_over": True, "fen": temp_board.fen()})
    try:
        raw_level = data.get("level")
        elo_rating = int(raw_level) if raw_level is not None else 200
    except (TypeError, ValueError):
        elo_rating = 200

    if elo_rating <= 200:    skill = 0
    elif elo_rating <= 400:  skill = 0
    elif elo_rating <= 800:  skill = 1
    elif elo_rating <= 1200: skill = 4
    elif elo_rating <= 1600: skill = 5
    elif elo_rating <= 2000: skill = 12
    elif elo_rating <= 2400: skill = 15
    else:                    skill = 20

    try:
        if elo_rating <= 200 and random.random() < 0.40:
            random_move = random.choice(list(temp_board.legal_moves))
            temp_board.push(random_move)
            with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
                info = engine.analyse(temp_board, chess.engine.Limit(time=0.01))
                score = info["score"].white()
                if score.is_mate(): eval_val = f"M{score.mate()}"
                else: eval_val = score.score() / 100.0 if score.score() is not None else 0.0
            board = temp_board
            return jsonify({"move": random_move.uci(), "fen": board.fen(), "evaluation": eval_val})

        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            engine.configure({"Skill Level": skill, "Threads": 1, "Hash": 16})
            limit = chess.engine.Limit(time=0.01, depth=1) if elo_rating <= 200 else chess.engine.Limit(time=0.01, nodes=(1000 if skill == 0 else None))
            result = engine.play(temp_board, limit)
            if result.move is None:
                return jsonify({"game_over": True, "fen": temp_board.fen()})
            temp_board.push(result.move)
            with chess.engine.SimpleEngine.popen_uci(engine_path) as engine2:
                info = engine2.analyse(temp_board, chess.engine.Limit(time=0.01))
                score = info["score"].white()
                eval_val = f"M{score.mate()}" if score.is_mate() else (score.score() / 100.0 if score.score() is not None else 0.0)
            board = temp_board
            return jsonify({"move": result.move.uci(), "fen": board.fen(), "evaluation": eval_val})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── HELPER FUNCTIONS ────────────────────────────────────────────────────────

def get_pins_and_attacks(board, square):
    is_pinned = board.is_pinned(board.turn, square)
    attackers = board.attackers(not board.turn, square)
    attacker_names = [chess.piece_name(board.piece_at(s).piece_type) for s in attackers if board.piece_at(s)]
    return is_pinned, attacker_names

def get_tactical_facts(board):
    facts = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece:
            pin_info = board.pin(piece.color, sq)
            if board.is_pinned(piece.color, sq):
                attackers = board.attackers(not piece.color, sq)
                for a_sq in attackers:
                    if a_sq in pin_info:
                        pinner = board.piece_at(a_sq)
                        facts.append(f"The {chess.piece_name(piece.piece_type)} on {chess.square_name(sq)} is pinned to the King by the {chess.piece_name(pinner.piece_type)} on {chess.square_name(a_sq)}.")
    return "\n".join(facts) if facts else "No absolute pins currently on the board."

def get_material_score(board):
    values = {
        chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
        chess.ROOK: 5, chess.QUEEN: 9
    }
    white_score = sum(len(board.pieces(pt, chess.WHITE)) * v for pt, v in values.items())
    black_score = sum(len(board.pieces(pt, chess.BLACK)) * v for pt, v in values.items())
    diff = white_score - black_score
    if diff == 0:   return "Material is even."
    elif diff > 0:  return f"White is +{diff} in material."
    else:           return f"Black is +{abs(diff)} in material."

def get_tactical_context(board, target_sq):
    facts = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == board.turn:
            if board.is_pinned(board.turn, sq):
                pinner_sq = board.attackers(not board.turn, sq)
                for ps in pinner_sq:
                    pinner = board.piece_at(ps)
                    facts.append(f"The {chess.piece_name(piece.piece_type)} on {chess.square_name(sq)} is pinned to the King by the {chess.piece_name(pinner.piece_type)} on {chess.square_name(ps)}.")
    attackers = board.attackers(not board.turn, target_sq)
    for a_sq in attackers:
        a_piece = board.piece_at(a_sq)
        facts.append(f"The {chess.piece_name(a_piece.piece_type)} on {chess.square_name(a_sq)} is attacking {chess.square_name(target_sq)}.")
    return "\n".join(facts) if facts else "No immediate pins or direct trades detected."

def get_game_phase(board):
    total_pieces = (len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK)) +
                    len(board.pieces(chess.ROOK, chess.WHITE))  + len(board.pieces(chess.ROOK, chess.BLACK)) +
                    len(board.pieces(chess.BISHOP, chess.WHITE))+ len(board.pieces(chess.BISHOP, chess.BLACK)) +
                    len(board.pieces(chess.KNIGHT, chess.WHITE))+ len(board.pieces(chess.KNIGHT, chess.BLACK)))
    move_count = len(board.move_stack)
    if move_count <= 10:      return "Opening"
    elif total_pieces <= 6:   return "Endgame"
    else:                     return "Middlegame"

def get_king_safety(board, color):
    king_sq = board.king(color)
    if king_sq is None:
        return "Unknown"
    enemy_color = not color
    attackers = len(board.attackers(enemy_color, king_sq))
    adjacent = chess.SquareSet(chess.BB_KING_ATTACKS[king_sq])
    adj_attacks = sum(1 for sq in adjacent if board.attackers(enemy_color, sq))
    if attackers > 0:
        return f"King is directly attacked by {attackers} piece(s). {adj_attacks} adjacent squares are also under fire — King is in DANGER."
    elif adj_attacks >= 3:
        return f"King zone is under heavy pressure ({adj_attacks} adjacent squares attacked)."
    elif adj_attacks >= 1:
        return f"King has mild exposure ({adj_attacks} adjacent squares attacked)."
    else:
        return "King appears safe."

def get_open_files(board):
    open_files, semi_open_white, semi_open_black = [], [], []
    for file_idx in range(8):
        file_name = chess.FILE_NAMES[file_idx]
        white_pawns = any(board.piece_at(chess.square(file_idx, r)) == chess.Piece(chess.PAWN, chess.WHITE) for r in range(8))
        black_pawns = any(board.piece_at(chess.square(file_idx, r)) == chess.Piece(chess.PAWN, chess.BLACK) for r in range(8))
        if not white_pawns and not black_pawns:  open_files.append(file_name)
        elif not white_pawns:                    semi_open_white.append(file_name)
        elif not black_pawns:                    semi_open_black.append(file_name)
    result = []
    if open_files:        result.append(f"Open files: {', '.join(open_files)}-file(s)")
    if semi_open_white:   result.append(f"Semi-open for White: {', '.join(semi_open_white)}-file(s)")
    if semi_open_black:   result.append(f"Semi-open for Black: {', '.join(semi_open_black)}-file(s)")
    return "; ".join(result) if result else "No open files."

def get_piece_activity(board):
    white_mobility = black_mobility = 0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.piece_type not in [chess.PAWN, chess.KING]:
            attacks = len(board.attacks(sq))
            if piece.color == chess.WHITE: white_mobility += attacks
            else:                          black_mobility += attacks
    return f"White piece activity: {white_mobility} squares controlled. Black piece activity: {black_mobility} squares controlled."


# ─── ADVANCED TACTICAL DETECTORS ─────────────────────────────────────────────

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 99
}

def piece_val(board, sq):
    p = board.piece_at(sq)
    return PIECE_VALUES.get(p.piece_type, 0) if p else 0

def pname(board, sq):
    p = board.piece_at(sq)
    return chess.piece_name(p.piece_type).capitalize() if p else "piece"

def sqname(sq):
    return chess.square_name(sq)

def get_recapture_info(board, move):
    to_sq = move.to_square
    moving_piece = board.piece_at(move.from_square)
    if not moving_piece:
        return None
    board.push(move)
    opponent = board.turn
    recapturers = list(board.attackers(opponent, to_sq))
    board.pop()
    if not recapturers:
        return None
    best_recapturer_sq = min(recapturers, key=lambda s: PIECE_VALUES.get(
        board.piece_at(s).piece_type if board.piece_at(s) else chess.PAWN, 99))
    recapturer = board.piece_at(best_recapturer_sq)
    if not recapturer:
        return None
    moved_value   = PIECE_VALUES.get(moving_piece.piece_type, 0)
    capture_value = piece_val(board, to_sq)
    recap_value   = PIECE_VALUES.get(recapturer.piece_type, 0)
    return {
        "can_recapture": True,
        "recapturer_piece": chess.piece_name(recapturer.piece_type).capitalize(),
        "recapturer_sq": sqname(best_recapturer_sq),
        "to_sq": sqname(to_sq),
        "moving_piece": chess.piece_name(moving_piece.piece_type).capitalize(),
        "moving_piece_value": moved_value,
        "recapturer_value": recap_value,
        "capture_value": capture_value,
        "material_lost": moved_value - capture_value,
    }

def detect_forks(board, move):
    board.push(move)
    to_sq = move.to_square
    moved_piece = board.piece_at(to_sq)
    if not moved_piece:
        board.pop()
        return None
    attacked_opponents = []
    for sq in board.attacks(to_sq):
        target = board.piece_at(sq)
        if target and target.color == board.turn:
            if target.piece_type != chess.PAWN or PIECE_VALUES.get(moved_piece.piece_type, 0) < PIECE_VALUES.get(target.piece_type, 0):
                attacked_opponents.append(f"{chess.piece_name(target.piece_type).capitalize()} on {sqname(sq)}")
    board.pop()
    if len(attacked_opponents) >= 2:
        return {
            "fork": True,
            "forking_piece": chess.piece_name(board.piece_at(move.from_square).piece_type).capitalize() if board.piece_at(move.from_square) else "Piece",
            "targets": attacked_opponents
        }
    return None

def get_hanging_pieces(board, color):
    hanging = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != color or piece.piece_type == chess.KING:
            continue
        attackers = list(board.attackers(not color, sq))
        defenders = list(board.attackers(color, sq))
        if attackers:
            min_attacker_val = min(PIECE_VALUES.get(board.piece_at(a).piece_type, 9) for a in attackers if board.piece_at(a))
            piece_value = PIECE_VALUES.get(piece.piece_type, 0)
            if not defenders or min_attacker_val < piece_value:
                attacker_sq = min(attackers, key=lambda a: PIECE_VALUES.get(board.piece_at(a).piece_type, 9) if board.piece_at(a) else 9)
                attacker_piece = board.piece_at(attacker_sq)
                hanging.append(
                    f"{chess.piece_name(piece.piece_type).capitalize()} on {sqname(sq)} "
                    f"(attacked by {chess.piece_name(attacker_piece.piece_type).capitalize()} on {sqname(attacker_sq)}, "
                    f"{'undefended' if not defenders else 'underdefended'})"
                )
    return hanging

def detect_discovered_attack(board, move):
    from_sq = move.from_square
    player_color = board.turn
    discovered = []
    piece = board.piece_at(from_sq)
    board.remove_piece_at(from_sq)
    for sq in chess.SQUARES:
        behind = board.piece_at(sq)
        if not behind or behind.color != player_color:
            continue
        if behind.piece_type not in [chess.BISHOP, chess.ROOK, chess.QUEEN]:
            continue
        for attack_sq in board.attacks(sq):
            target = board.piece_at(attack_sq)
            if target and target.color != player_color and target.piece_type != chess.PAWN:
                discovered.append(
                    f"{chess.piece_name(behind.piece_type).capitalize()} on {sqname(sq)} "
                    f"reveals attack on {chess.piece_name(target.piece_type).capitalize()} on {sqname(attack_sq)}"
                )
    board.set_piece_at(from_sq, piece)
    return discovered

def detect_skewers(board, move):
    board.push(move)
    to_sq = move.to_square
    moved = board.piece_at(to_sq)
    opponent = board.turn
    skewers = []
    if not moved or moved.piece_type not in [chess.BISHOP, chess.ROOK, chess.QUEEN]:
        board.pop()
        return skewers
    for attack_sq in board.attacks(to_sq):
        front = board.piece_at(attack_sq)
        if not front or front.color != opponent:
            continue
        front_val = PIECE_VALUES.get(front.piece_type, 0)
        direction = (chess.square_file(attack_sq) - chess.square_file(to_sq),
                     chess.square_rank(attack_sq) - chess.square_rank(to_sq))
        next_file = chess.square_file(attack_sq) + (1 if direction[0] > 0 else -1 if direction[0] < 0 else 0)
        next_rank = chess.square_rank(attack_sq) + (1 if direction[1] > 0 else -1 if direction[1] < 0 else 0)
        if 0 <= next_file <= 7 and 0 <= next_rank <= 7:
            behind_sq = chess.square(next_file, next_rank)
            behind = board.piece_at(behind_sq)
            if behind and behind.color == opponent:
                behind_val = PIECE_VALUES.get(behind.piece_type, 0)
                if front_val > behind_val:
                    skewers.append(
                        f"Skewer: {chess.piece_name(moved.piece_type).capitalize()} on {sqname(to_sq)} "
                        f"attacks {chess.piece_name(front.piece_type).capitalize()} on {sqname(attack_sq)}, "
                        f"with {chess.piece_name(behind.piece_type).capitalize()} on {sqname(behind_sq)} behind it"
                    )
    board.pop()
    return skewers

def detect_back_rank_weakness(board, color):
    back_rank = 0 if color == chess.WHITE else 7
    king_sq = board.king(color)
    if not king_sq or chess.square_rank(king_sq) != back_rank:
        return None
    pawns_blocking = 0
    for file in range(max(0, chess.square_file(king_sq)-1), min(8, chess.square_file(king_sq)+2)):
        sq = chess.square(file, back_rank)
        p = board.piece_at(sq)
        if p and p.piece_type == chess.PAWN and p.color == color:
            pawns_blocking += 1
    if pawns_blocking >= 2:
        opponent = not color
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.color == opponent and p.piece_type in [chess.ROOK, chess.QUEEN]:
                if chess.square_rank(sq) != back_rank:
                    return f"Back rank weakness: King on {sqname(king_sq)} is blocked by own pawns — vulnerable to back rank mate from {chess.piece_name(p.piece_type).capitalize()} on {sqname(sq)}"
    return None

def get_pawn_structure(board):
    facts = []
    for color in [chess.WHITE, chess.BLACK]:
        color_name = "White" if color == chess.WHITE else "Black"
        pawns = list(board.pieces(chess.PAWN, color))
        files = [chess.square_file(p) for p in pawns]
        for f in set(files):
            if files.count(f) > 1:
                facts.append(f"{color_name} has doubled pawns on the {chess.FILE_NAMES[f]}-file")
        for p in pawns:
            f = chess.square_file(p)
            neighbors = [chess.square_file(x) for x in pawns if x != p]
            if (f-1) not in neighbors and (f+1) not in neighbors:
                facts.append(f"{color_name} has an isolated pawn on {sqname(p)}")
        opponent = not color
        opp_pawns = list(board.pieces(chess.PAWN, opponent))
        for p in pawns:
            f = chess.square_file(p)
            r = chess.square_rank(p)
            is_passed = True
            for op in opp_pawns:
                of = chess.square_file(op)
                or_ = chess.square_rank(op)
                if abs(of - f) <= 1:
                    if (color == chess.WHITE and or_ > r) or (color == chess.BLACK and or_ < r):
                        is_passed = False
                        break
            if is_passed:
                facts.append(f"{color_name} has a passed pawn on {sqname(p)}")
    return "; ".join(facts) if facts else "No notable pawn structure issues."

def full_move_analysis(board, move):
    result = {
        "is_legal": move in board.legal_moves,
        "is_capture": board.is_capture(move),
        "gives_check": board.gives_check(move),
        "is_castling": board.is_castling(move),
        "is_en_passant": board.is_en_passant(move),
        "recapture": None, "fork": None,
        "discovered_attacks": [], "skewers": [],
        "hanging_before": [], "hanging_after": [],
        "back_rank_before": None, "back_rank_after": None,
        "pawn_structure": "",
    }
    if not result["is_legal"]:
        return result
    moving_piece = board.piece_at(move.from_square)
    captured_piece = board.piece_at(move.to_square)
    result["captured_piece"]  = chess.piece_name(captured_piece.piece_type).capitalize() if captured_piece else None
    result["captured_value"]  = PIECE_VALUES.get(captured_piece.piece_type, 0) if captured_piece else 0
    result["moving_piece"]    = chess.piece_name(moving_piece.piece_type).capitalize() if moving_piece else None
    result["moving_value"]    = PIECE_VALUES.get(moving_piece.piece_type, 0) if moving_piece else 0
    result["recapture"]       = get_recapture_info(board, move)
    result["fork"]            = detect_forks(board, move)
    result["discovered_attacks"] = detect_discovered_attack(board, move)
    result["skewers"]         = detect_skewers(board, move)
    player = board.turn
    result["hanging_before"]  = get_hanging_pieces(board, player)
    board.push(move)
    result["hanging_after"]   = get_hanging_pieces(board, not player)
    result["back_rank_after"] = detect_back_rank_weakness(board, not player)
    result["pawn_structure"]  = get_pawn_structure(board)
    board.pop()
    result["back_rank_before"] = detect_back_rank_weakness(board, not player)
    return result

def format_move_analysis_for_prompt(analysis, move_san):
    lines = []
    lines.append(f"MOVE: {move_san}")
    lines.append(f"Is Capture: {analysis['is_capture']} (captured: {analysis.get('captured_piece','nothing')}, value: {analysis.get('captured_value',0)} pts)")
    lines.append(f"Gives Check: {analysis['gives_check']}")
    lines.append(f"Is Castling: {analysis['is_castling']}")
    lines.append(f"Is En Passant: {analysis['is_en_passant']}")

    if analysis["recapture"]:
        r = analysis["recapture"]
        captured_val = analysis.get('captured_value', 0)
        captured_name = analysis.get('captured_piece', 'piece') or 'piece'
        net_loss = r['moving_piece_value'] - captured_val
        lines.append(
            f"RECAPTURE WARNING: Your {r['moving_piece']} captures the {captured_name} on {r['to_sq']} "
            f"(worth {captured_val} pts), BUT opponent's {r['recapturer_piece']} on {r['recapturer_sq']} "
            f"immediately takes back your {r['moving_piece']} on {r['to_sq']} (worth {r['moving_piece_value']} pts). "
            f"You gain {captured_val} pts but lose {r['moving_piece_value']} pts — net loss of {net_loss} pts. "
            f"This is NOT a free capture."
        )
    else:
        lines.append("Recapture: No opponent piece can recapture on the destination square.")

    if analysis["fork"]:
        f = analysis["fork"]
        lines.append(f"FORK CREATED: {f['forking_piece']} forks {', '.join(f['targets'])}")
    if analysis["discovered_attacks"]:
        lines.append("DISCOVERED ATTACKS: " + "; ".join(analysis["discovered_attacks"]))
    if analysis["skewers"]:
        lines.append("SKEWERS: " + "; ".join(analysis["skewers"]))
    if analysis["hanging_before"]:
        lines.append("YOUR PIECES HANGING BEFORE MOVE: " + "; ".join(analysis["hanging_before"]))
    if analysis["hanging_after"]:
        lines.append("OPPONENT PIECES HANGING AFTER MOVE: " + "; ".join(analysis["hanging_after"]))
    if analysis["back_rank_before"]:
        lines.append(f"BACK RANK THREAT (before move): {analysis['back_rank_before']}")
    if analysis["back_rank_after"]:
        lines.append(f"BACK RANK THREAT (after move): {analysis['back_rank_after']}")
    lines.append(f"Pawn Structure: {analysis['pawn_structure']}")
    return "\n".join(lines)


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route('/game_summary', methods=['POST'])
def game_summary():
    data = request.json
    pgn = data.get('pgn')
    bot_elo = data.get('bot_elo', 400)
    player_color = data.get('player_color', 'white')
    player_side  = "White" if player_color == 'white' else "Black"
    engine_side  = "Black" if player_color == 'white' else "White"

    if not pgn:
        return jsonify({"status": "error", "message": "No game history found."})

    try:
        response = client.chat.completions.create(
            model=DEFAULT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": f"""You are 'James', a high-level Chess Coach.
                You are reviewing a game where the STUDENT played as {player_side} and the {bot_elo} ELO bot played as {engine_side}.

                CRITICAL INSTRUCTIONS:
                1. Analyze only the moves in the provided PGN. Do not mention any move that did not appear.
                2. Identify the opening and the turning point where the position changed.
                3. Explain the turning point in concrete chess terms, not engine numbers.
                4. Always refer to the student's moves as {player_side}'s moves and the bot's moves as {engine_side}'s moves.
                5. Format exactly three sections: Opening Analysis, Turning Point, Coach's Tip for Improvement.
                6. Use markdown emphasis for SAN only. No bullet lists, no extra headers, no engine scores.
                7. If the PGN is incomplete or illegal, say that clearly.
                """},
                {"role": "user", "content": f"Here is the game PGN:\n{pgn}\n\nPlease summarize my performance."}
            ],
            temperature=0.7
        )
        summary_text = response.choices[0].message.content
        return jsonify({"status": "success", "summary": summary_text})
    except Exception as e:
        print(f"Error in summary: {e}")
        return jsonify({"status": "error", "message": str(e)})


@app.route('/explain_move', methods=['POST'])
def explain_move():
    global board
    data = request.json or {}
    mode = data.get("mode", "analysis")
    player_color = data.get("player_color", "white")
    frontend_history = data.get("history", [])

    if frontend_history:
        temp_board = chess.Board()
        for san in frontend_history:
            try:
                move = temp_board.parse_san(san)
                temp_board.push(move)
            except Exception:
                pass
        board = temp_board.copy()
    else:
        temp_board = board.copy()

    if len(temp_board.move_stack) == 0:
        return jsonify({"status": "error", "message": "Make a move first!"})

    try:
        if mode == 'play' and len(temp_board.move_stack) >= 2:
            player_chess_color = chess.BLACK if player_color == 'black' else chess.WHITE
            if temp_board.turn == player_chess_color:
                temp_board.pop()

        user_move = temp_board.pop()
        fen_before = temp_board.fen()
        prev_eval = get_evaluation(fen_before)

        missed_best_move = "None"
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info_before = engine.analyse(temp_board, chess.engine.Limit(time=0.1))
            if "pv" in info_before and len(info_before["pv"]) > 0:
                missed_best_move = temp_board.san(info_before["pv"][0])

        moving_piece = temp_board.piece_at(user_move.from_square)
        moving_piece_name = chess.piece_name(moving_piece.piece_type).capitalize() if moving_piece else "Piece"
        san_move = temp_board.san(user_move)

        temp_board.push(user_move)
        fen_after = temp_board.fen()
        current_eval = get_evaluation(fen_after)

        punishment_move = "None"
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info_after = engine.analyse(temp_board, chess.engine.Limit(time=0.1))
            if "pv" in info_after and len(info_after["pv"]) > 0:
                punishment_move = temp_board.san(info_after["pv"][0])

        punishing_piece = "opponent"
        if punishment_move != "None":
            p_char = punishment_move[0]
            piece_map = {'Q': 'Queen', 'R': 'Rook', 'B': 'Bishop', 'N': 'Knight', 'K': 'King'}
            punishing_piece = piece_map.get(p_char, "Pawn")

        category = "Good/Positional Move"
        eval_delta = 0.0
        try:
            def parse_eval(e):
                if isinstance(e, str) and "M" in e:
                    return 20.0 if not "-" in e else -20.0
                return float(e)
            p_val = parse_eval(prev_eval)
            c_val = parse_eval(current_eval)
            eval_delta = c_val - p_val
            turn_count = len(temp_board.move_stack)
            if temp_board.is_checkmate():
                category = "Checkmate"
            elif isinstance(current_eval, str) and "M-" in current_eval:
                category = "Missing Checkmate"
            elif p_val > 2.5 and eval_delta < -2.0:
                category = "Missed Win"
            elif eval_delta <= -3.0:
                category = "Blunder"
            elif eval_delta <= -1.2:
                category = "Mistake"
            elif eval_delta <= -0.6:
                category = "Inaccuracy"
            elif turn_count <= 10 and eval_delta >= -0.4:
                category = "Opening/Book Move"
        except Exception as math_e:
            print(f"Eval Math Error: {math_e}")

        ai_facing_punishment = punishment_move if category not in ["Opening/Book Move", "Good/Positional Move"] else "N/A"

        piece_positions = get_piece_positions(temp_board)
        prompt = f"""
        DATA:
        - Piece Moved: {moving_piece_name}
        - Move Played: {san_move}
        - Move Category: {category}
        - Evaluation Change: {round(eval_delta, 2)} points
        - Engine's Best Next Move (Opponent Response): {ai_facing_punishment}
        - Punishing Piece: {punishing_piece}
        - Missed Best Move: {missed_best_move}
        - Current Piece Locations: {piece_positions}
        - Current Board FEN: {fen_after}

        TASK:
        Based on the 'Move Category' of [{category}], explain the move {san_move}.
        - If [{category}] is 'Checkmate', state clearly that this move delivers checkmate and describe the final mate net using only the provided pieces and squares.
        - If [{category}] is 'Inaccuracy', 'Mistake', 'Blunder', or 'Missing Checkmate', use the provided 'Engine's Best Next Move' and the exact current piece locations to explain how the opponent's {punishing_piece} punishes the user.
        - If [{category}] is 'Missed Win', strictly focus on how they failed to play {missed_best_move} and what {missed_best_move} would have achieved.
        - If [{category}] is 'Opening/Book Move' or 'Good/Positional', ignore the opponent's next move and missed move. Only explain why {san_move} works well.
        - Use only the pieces and squares listed in Current Piece Locations. Do not invent any square or piece identity.
        """
        response = client.chat.completions.create(
            model=DEFAULT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        return jsonify({"status": "success", "explanation": response.choices[0].message.content})

    except Exception as e:
        print(f"!!! OPENAI COACH ERROR: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to analyze move."})


@app.route('/best_move', methods=['POST'])
def best_move():
    data = request.json
    current_fen = data.get("fen")
    move_number = (len(board.move_stack) // 2) + 1
    temp_board = chess.Board(current_fen) if current_fen else chess.Board()

    if temp_board.is_game_over():
        return jsonify({"status": "error", "message": "The game is already over!"})

    material_status = get_material_score(temp_board)
    tactical_facts  = get_tactical_facts(temp_board)

    try:
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info = engine.analyse(temp_board, chess.engine.Limit(time=1.5))
            best_move_obj = info["pv"][0]
            san_move = temp_board.san(best_move_obj)
            pv_san = []
            test_board = temp_board.copy()
            for m in info["pv"][:4]:
                turn_label = "White" if test_board.turn == chess.WHITE else "Black"
                # Annotate captures with exact piece name so GPT cannot guess wrong
                if test_board.is_capture(m):
                    captured = test_board.piece_at(m.to_square)
                    if captured:
                        cap_name = chess.piece_name(captured.piece_type).capitalize()
                        cap_sq   = chess.square_name(m.to_square)
                        pv_san.append(f"{turn_label} plays {test_board.san(m)} (capturing the {cap_name} on {cap_sq})")
                    else:
                        pv_san.append(f"{turn_label} plays {test_board.san(m)}")
                else:
                    pv_san.append(f"{turn_label} plays {test_board.san(m)}")
                test_board.push(m)
            expected_line_list = "\n".join([f"- {m}" for m in pv_san])
            game_history = []
            hist_board = chess.Board()
            for move in board.move_stack:
                game_history.append(hist_board.san(move))
                hist_board.push(move)
            moving_piece = temp_board.piece_at(best_move_obj.from_square)
            moving_piece_name = chess.piece_name(moving_piece.piece_type).capitalize() if moving_piece else "Piece"

        tactical_facts = get_tactical_facts(temp_board)
        piece_positions = get_piece_positions(temp_board)

        prompt = f"""
            DATA:
            - Move Number: {move_number}
            - Recommended Move: {san_move}
            - Piece Moving: {moving_piece_name}
            - Material Status: {material_status}
            - Tactical Facts (Ground Truth): {tactical_facts}
            - Engine's Expected Continuation: {expected_line_list}
            - Current Board FEN: {temp_board.fen()}
            - CURRENT PIECE LOCATIONS (authoritative — use ONLY these to identify what is on each square, never infer from move history): {piece_positions}

            TASK:
            Explain exactly WHY {san_move} is the best move.
            
            STRICT RULES:
            1. **The "Copy-Paste" Rule:** When mentioning the opponent's best response, YOU MUST copy the move EXACTLY as it appears in the 'Engine's Expected Continuation'. If the data says "Black plays Ke6", YOU MUST NOT say "Black plays Be6" or "Black blocks with the bishop." 
            2. **Coordinate Lockdown:** Do not mention any square (like e7 or d5) unless it is explicitly mentioned in the 'Tactical Facts' or 'Expected Continuation'. 
            3. **Piece Identity:** Before naming any piece on any square, look it up in CURRENT PIECE LOCATIONS. Never call a Bishop a Rook. Never infer piece identity from move history.
            4. **The "Best Reply" Rule:** Use phrases like "The best response is [EXACT MOVE FROM DATA], but you still maintain the initiative."
            5. Tone: Practical, blunt, and instructive. Max 3 sentences.
            """
        response = client.chat.completions.create(
            model=DEFAULT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        return jsonify({
            "status": "success",
            "move": san_move,
            "from_sq": best_move_obj.from_square,
            "to_sq": best_move_obj.to_square,
            "explanation": response.choices[0].message.content
        })
    except Exception as e:
        print(f"!!! BEST MOVE ERROR: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to suggest a move."})


@app.route('/sync_position', methods=['POST'])
def sync_position():
    global board
    data = request.json
    fen     = data.get('fen')
    history = data.get('history', [])
    if not fen:
        return jsonify({"status": "error", "message": "No FEN provided"})
    try:
        board = chess.Board()
        for san in history:
            move = board.parse_san(san)
            board.push(move)
        evaluation = get_evaluation(board.fen())
        return jsonify({"status": "success", "evaluation": evaluation})
    except Exception as e:
        try:
            board = chess.Board(fen)
            evaluation = get_evaluation(fen)
            return jsonify({"status": "success", "evaluation": evaluation})
        except Exception as e2:
            return jsonify({"status": "error", "message": str(e2)})


@app.route('/load_pgn', methods=['POST'])
def load_pgn():
    global board
    data = request.json
    pgn_text = data.get('pgn', '').strip()
    if not pgn_text:
        return jsonify({"status": "error", "message": "No PGN provided."})

    try:
        pgn_io = io.StringIO(pgn_text)
        game_pgn = chess.pgn.read_game(pgn_io)
        if game_pgn is None:
            return jsonify({"status": "error", "message": "Unable to parse PGN."})

        board = chess.Board()
        for move in game_pgn.mainline_moves():
            board.push(move)

        evaluation = get_evaluation(board.fen())
        return jsonify({"status": "success", "fen": board.fen(), "evaluation": evaluation})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ─── EVALUATE USER SUGGESTED MOVE ────────────────────────────────────────────

def evaluate_user_suggested_move(board, user_message, history=None):
    import re

    def normalize_move(m):
        if m and m[0] in 'kqrbn':
            return m[0].upper() + m[1:]
        return m

    raw_matches = re.findall(
        r'\b([KQRBNkqrbn]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBNqrbn])?|O-O-O|O-O|0-0-0|0-0)\b',
        user_message
    )

    for raw in raw_matches:
        move_str = normalize_move(raw)

        # ── STEP 1: Legality check (isolated try-except) ──────────────────────
        # If this fails, the move is genuinely illegal — skip to next match.
        # We separate this from Stockfish so a Stockfish error never causes
        # a legal move to be silently discarded and wrongly flagged as illegal.
        move = None
        try:
            move = board.parse_san(move_str)
            if move not in board.legal_moves:
                move = None
        except Exception:
            move = None

        if move is None:
            continue  # Genuinely not legal — try next regex match

        # ── STEP 2: Move IS legal. Run Stockfish analysis. ────────────────────
        mover_is_black = (board.turn == chess.BLACK)
        try:
            eval_before = get_evaluation(board.fen())
            board.push(move)
            eval_after = get_evaluation(board.fen())

            best_reply = "N/A"
            continuation = []
            try:
                with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
                    info = engine.analyse(board, chess.engine.Limit(time=0.4))
                    if "pv" in info and info["pv"]:
                        best_reply = board.san(info["pv"][0])
                        test_b = board.copy()
                        for m in info["pv"][:4]:
                            label = "White" if test_b.turn == chess.WHITE else "Black"
                            continuation.append(f"{label}: {test_b.san(m)}")
                            test_b.push(m)
            except Exception:
                pass

            board.pop()

            def parse_e(e):
                if isinstance(e, str) and "M" in e:
                    return 20.0 if "-" not in e else -20.0
                return float(e)

            # Stockfish eval is always from White's perspective.
            # Negate delta for Black's moves so positive = good for the mover.
            delta = parse_e(eval_after) - parse_e(eval_before)
            if mover_is_black:
                delta = -delta

            if delta >= 0.5:      verdict = "STRONG"
            elif delta >= -0.3:   verdict = "REASONABLE"
            elif delta >= -1.0:   verdict = "INACCURACY"
            elif delta >= -2.0:   verdict = "MISTAKE"
            else:                 verdict = "BLUNDER"

            verdict_plain = {
                "STRONG":     "a strong move that improves your position",
                "REASONABLE": "a reasonable move — not the best but not losing",
                "INACCURACY": "an inaccuracy — it slightly weakens your position",
                "MISTAKE":    "a mistake — it gives your opponent a clear advantage",
                "BLUNDER":    "a blunder — it loses significant material or causes serious damage",
            }.get(verdict, verdict)

            tactical = full_move_analysis(board, move)
            tactical_str = format_move_analysis_for_prompt(tactical, move_str)

            return {
                "move": move_str,
                "verdict": verdict,
                "verdict_plain": verdict_plain,
                "best_reply_after": best_reply,
                "continuation": " -> ".join(continuation),
                "tactical_analysis": tactical_str
            }

        except Exception:
            # Stockfish failed but the move IS confirmed legal.
            # Return a partial result so the move is NOT wrongly flagged as illegal.
            try:
                board.pop()
            except Exception:
                pass
            return {
                "move": move_str,
                "verdict": "UNKNOWN",
                "verdict_plain": "a legal move (engine analysis temporarily unavailable)",
                "best_reply_after": "N/A",
                "continuation": "",
                "tactical_analysis": f"MOVE: {move_str}\nStockfish analysis unavailable — treat as a legal move."
            }

    return None


# ─── ASK COACH ROUTE ─────────────────────────────────────────────────────────

def get_piece_positions(board):
    positions = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p:
            color = "White" if p.color == chess.WHITE else "Black"
            positions.append(
                f"{color} {chess.piece_name(p.piece_type).capitalize()} on {chess.square_name(sq)}"
            )
    return ", ".join(positions) if positions else "No pieces on board."


def did_coach_ask_question(conversation_log):
    if not conversation_log:
        return False
    for entry in reversed(conversation_log):
        if entry.get("role") == "assistant":
            return entry.get("content", "").strip().endswith("?")
    return False


def is_direct_question(text):
    if not text:
        return False
    normalized = text.lower()
    question_words = ["why", "how", "what", "can i", "should i", "does", "do i", "is it", "would", "could"]
    if "?" in normalized:
        return True
    return any(word in normalized for word in question_words)

@app.route('/ask_coach', methods=['POST'])
def ask_coach():
    global board
    data = request.json or {}

    user_question    = data.get("question", "").strip()
    fen              = data.get("fen", "")
    pgn              = data.get("pgn", "")
    history          = data.get("history", [])
    current_eval     = data.get("eval", 0)
    player_color     = data.get("player_color", "white")
    game_mode        = data.get("game_mode", "analysis")
    bot_elo          = data.get("bot_elo", None)
    move_number      = data.get("move_number", 1)
    conversation_log = data.get("conversation_log", [])

    if not user_question:
        return jsonify({"status": "error", "message": "No question received."})

    try:
        temp_board = chess.Board()
        for san in history:
            temp_board.push(temp_board.parse_san(san))
    except Exception:
        try:
            temp_board = chess.Board(fen) if fen else chess.Board()
        except Exception:
            temp_board = chess.Board()

    material          = get_material_score(temp_board)
    tactical_facts    = get_tactical_facts(temp_board)
    game_phase        = get_game_phase(temp_board)
    open_files        = get_open_files(temp_board)
    piece_activity    = get_piece_activity(temp_board)
    white_king_safety = get_king_safety(temp_board, chess.WHITE)
    black_king_safety = get_king_safety(temp_board, chess.BLACK)
    whose_turn        = "White" if temp_board.turn == chess.WHITE else "Black"
    in_check          = "YES — the king is in check." if temp_board.is_check() else "No."

    engine_best = "N/A"
    engine_continuation = []
    try:
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info = engine.analyse(temp_board, chess.engine.Limit(time=0.5))
            if "pv" in info and info["pv"]:
                engine_best = temp_board.san(info["pv"][0])
                test_b = temp_board.copy()
                for m in info["pv"][:5]:
                    label = "White" if test_b.turn == chess.WHITE else "Black"
                    engine_continuation.append(f"{label}: {test_b.san(m)}")
                    test_b.push(m)
    except Exception:
        pass

    continuation_str = " → ".join(engine_continuation) if engine_continuation else "N/A"

    suggested_move_analysis = evaluate_user_suggested_move(temp_board, user_question, history)
    suggested_move_str = "NONE — user did not mention a specific move."
    if suggested_move_analysis:
        sm = suggested_move_analysis
        suggested_move_str = (
            f"MOVE MENTIONED: {sm['move']}\n"
            f"Stockfish Verdict: {sm['verdict']} — {sm['verdict_plain']}\n"
            f"[COACH EYES ONLY — DO NOT STATE THIS TO THE STUDENT IN MODE 1]: "
            f"The punishment move is {sm['best_reply_after']}. "
            f"Engine line after student's move: {sm['continuation']}\n"
            f"--- FULL TACTICAL BREAKDOWN ---\n"
            f"{sm['tactical_analysis']}"
        )
    else:
        # ── Illegal move detection ─────────────────────────────────────────
        # evaluate_user_suggested_move returned None — check if the user
        # mentioned something that looks like a move but is genuinely illegal.
        # We only fire the ILLEGAL MOVE ALERT when we can POSITIVELY confirm
        # the move is not legal — never fire on ambiguity or Stockfish failure
        # (those are caught above and return a partial result instead).
        import re as _re
        _move_pattern = _re.findall(
            r'\b([KQRBNkqrbn]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBNqrbn])?|O-O-O|O-O|0-0-0|0-0)\b',
            user_question
        )
        def _normalize(m):
            return m[0].upper() + m[1:] if m and m[0] in 'kqrbn' else m
        if _move_pattern:
            mentioned = _normalize(_move_pattern[0])
            # Default: NOT illegal (avoid false positives)
            is_illegal = False
            try:
                parsed = temp_board.parse_san(mentioned)
                # parse_san succeeded — is it actually in legal_moves?
                if parsed not in temp_board.legal_moves:
                    is_illegal = True
            except Exception:
                # parse_san raised — the move notation is genuinely unplayable
                is_illegal = True

            if is_illegal:
                # Build a concrete reason from piece positions
                piece_pos = get_piece_positions(temp_board)
                suggested_move_str = (
                    f"⚠️ ILLEGAL MOVE ALERT ⚠️: The move '{mentioned}' is NOT in the list of "
                    f"legal moves for this position. Verified against the board — it cannot be played.\n"
                    f"MANDATORY RESPONSE RULES:\n"
                    f"1. Your FIRST sentence MUST be: 'That move is illegal.'\n"
                    f"2. Then explain the specific reason using CURRENT PIECE LOCATIONS — "
                    f"which piece cannot reach that square, or which square is empty, "
                    f"or why the move geometry is wrong.\n"
                    f"3. DO NOT say the move is reasonable, possible, or describe what it would accomplish.\n"
                    f"4. DO NOT apologize or say you made an error previously — just state clearly it is illegal.\n"
                    f"Current piece locations for your reference: {piece_pos}"
                )

    if isinstance(current_eval, str) and "M" in str(current_eval):
        eval_str = f"Forced mate in {current_eval}"
    else:
        try:
            ev = float(current_eval)
            if ev > 0:    eval_str = f"+{ev:.2f} (White is better)"
            elif ev < 0:  eval_str = f"{ev:.2f} (Black is better)"
            else:         eval_str = "0.00 (Equal position)"
        except Exception:
            eval_str = str(current_eval)

    piece_positions = get_piece_positions(temp_board)
    opponent_str = f"{bot_elo} ELO bot" if bot_elo and game_mode == "play" else "human opponent" if game_mode == "play" else "N/A (Analysis mode)"

    context_block = f"""
=== COMPLETE GAME CONTEXT FOR COACH ===
Game Mode: {game_mode.upper()} - Player is {player_color.capitalize()}{" vs " + opponent_str if game_mode == "play" else " (Analysis Board)"}
Move Number: {move_number} | Whose Turn: {whose_turn} | King In Check: {in_check}

--- POSITION (GROUND TRUTH) ---
FEN: {fen}
CURRENT PIECE LOCATIONS (authoritative — every piece exactly where it is RIGHT NOW):
{piece_positions}
Game Phase: {game_phase}
Stockfish Evaluation: {eval_str}
Engine Best Move HERE: {engine_best}
Engine Continuation: {continuation_str}

--- MATERIAL & TACTICS (ONLY REFERENCE THESE FACTS) ---
Material Balance: {material}
Active Pins: {tactical_facts}
Piece Mobility: {piece_activity}
Open Files: {open_files}
White King Safety: {white_king_safety}
Black King Safety: {black_king_safety}

--- MOVE HISTORY ---
{pgn if pgn else " ".join(history) if history else "No moves yet."}

--- STOCKFISH VERDICT ON USER MENTIONED MOVE ---
{suggested_move_str}
=== END CONTEXT ===
"""

    coach_system_prompt = (
        f"You are a chess coach. The student is {player_color.capitalize()}"
        f"{' vs a ' + opponent_str if game_mode == 'play' else ' in analysis mode'}. "
        f"Game phase: {game_phase}.\n\n"

        "=== YOUR JOB ===\n"
        "Help the student understand chess through their own thinking. "
        "When a move is bad, guide them to discover the punishment — do not hand them the answer immediately. "
        "When they guess, respond based on whether they got it right or wrong. "
        "When they ask a general question, answer it directly and specifically.\n\n"

        "=== ABSOLUTE RULES — NEVER BREAK THESE ===\n"
        "RULE 1: CURRENT PIECE LOCATIONS in the CONTEXT is the ONLY truth for what is on each square. "
        "Never use move history, PGN, or outside knowledge to infer where pieces currently are. "
        "If the context does not list a piece on a square, do not say it is there.\n"
        "RULE 2: If the student mentions a specific move and it is illegal, your first sentence must be exactly: 'That move is illegal.' "
        "Then explain the concrete reason using CURRENT PIECE LOCATIONS.\n"
        "RULE 3: If the student mentions a legal candidate move, judge it from the current board and compare it to the engine's best continuation when useful. "
        "Say whether it is sound, tactical, or flawed, and explain why in exact pieces/squares.\n"
        "RULE 4: If the student asks a direct question about the position, answer directly and avoid repeating the same move or capture phrase twice. State the capturing piece once, describe the material result once, and do not ask a new question back.\n"
        "RULE 5: If you do ask a follow-up question, make it a new question about the resulting placement, the capturing piece, or the concrete consequence on the board.\n"
        "RULE 6: Never mention eval scores, centipawns, mate distance, or any engine number. "
        "Use only chess language such as loses material, strong move, bad trade, or winning initiative.\n"
        "RULE 7: Never say Great question, Certainly, Of course, Sure, or any filler. "
        "Your first word must be about chess.\n"
        "RULE 8: Do not use bullet points, numbered lists, or headers in your final answer.\n"
        "RULE 9: Do not mention more than 4 sentences total.\n"
        "RULE 10: Only mention pieces and squares that appear in CURRENT PIECE LOCATIONS or Engine Continuation.\n\n"

        "=== QUESTION TYPES TO HANDLE ===\n"
        "Specific candidate move questions: 'Is Nf6 good?', 'What about Qh5?', 'Can I play g4?', 'I was thinking of playing Nxg5.'\n"
        "Tactical failure questions: 'Why is Bc4 bad?', 'Why doesn't Nxd5 work?', 'What is the threat?'\n"
        "Plan questions: 'Should I castle?', 'How do I improve my bishop?', 'What should I do next?'\n"
        "Exchange questions: 'Is this trade good?', 'Should I give up the bishop?', 'How do I simplify?'\n"
        "Legality questions: 'Is Qh5 legal?', 'Can I play e5?', 'Why can't I move the knight to f3?'\n"
        "Follow-up answers to the coach's previous question: judge whether the student's answer is correct and why.\n\n"
        "=== HOW TO READ THE CONTEXT ===\n"
        "The CONTEXT contains a section called STOCKFISH VERDICT ON USER MENTIONED MOVE. "
        "Inside it, there is a line marked [COACH EYES ONLY — DO NOT STATE THIS TO THE STUDENT IN MODE 1]. "
        "That line tells you the punishment move the opponent would play. "
        "You KNOW this move, but in MODE 1 you must NOT reveal it. Your job is to ask the student to find it.\n\n"

        "=== SITUATION GUIDE ===\n\n"

        "SITUATION A — Student suggests a move and Stockfish says it is INACCURACY, MISTAKE, or BLUNDER:\n"
        "Sentence 1: Acknowledge the valid part of the student's thinking. "
        "Be specific — mention the exact piece and what it does right (e.g. it does grab a pawn, it does attack a square).\n"
        "Sentence 2: Explain the specific tactical problem using CURRENT PIECE LOCATIONS. "
        "Say which piece of theirs is left undefended, or which square becomes weak, or what threat appears. "
        "Be concrete — name the exact piece and square from CURRENT PIECE LOCATIONS.\n"
        "Sentence 3: If the student's message is a direct question about the candidate move, answer it directly instead of asking another question. "
        "If it is not a direct question, ask the student one specific guiding question that points them toward finding the opponent's punishment move. "
        "Do NOT name the punishment move. Do NOT say what it captures. Just ask them to find it by pointing at the relevant area of the board.\n\n"

        "SITUATION B — Previous coach message asked the student a question, and student's answer is CORRECT "
        "(matches or describes the punishment move in COACH EYES ONLY):\n"
        "Sentence 1: Confirm they are correct. One word or short phrase only — do not be verbose about the confirmation.\n"
        "Sentence 2: Explain concisely why that move is the punishment, using the exact pieces and squares from CURRENT PIECE LOCATIONS and Engine Continuation.\n"
        "Sentence 3: Give one practical improvement tip that is directly relevant to this position — "
        "something actionable the student can apply right now, like a specific piece to develop, "
        "a king safety issue to address, or a positional concept demonstrated by this exact position. "
        "Tie it to a specific piece or square from the board.\n\n"

        "SITUATION C — Previous coach message asked the student a question, and student's answer is WRONG "
        "(does not match the punishment move in COACH EYES ONLY):\n"
        "Sentence 1: Tell them that is not the move, briefly and without harsh criticism.\n"
        "Sentence 2: Reveal the actual punishment move from COACH EYES ONLY and explain exactly why it works, "
        "using CURRENT PIECE LOCATIONS. Name the piece, the square it moves to, and what it wins.\n"
        "Sentence 3: Give one practical improvement tip tied to a specific piece or square in the current position — "
        "the same quality of tip as in SITUATION B.\n\n"

        "SITUATION D — Student asks why a move does NOT work, or asks a how/why/what question about the position:\n"
        "Answer directly and specifically using only CURRENT PIECE LOCATIONS, Tactical Facts, and Engine Continuation from CONTEXT. "
        "Explain the concrete reason — name the piece, the square, the consequence. "
        "No abstract principles unless tied directly to a piece currently on the board.\n\n"

        "SITUATION E — Student suggests a move and Stockfish says it is STRONG or REASONABLE:\n"
        "Sentence 1: Confirm the move is good.\n"
        "Sentence 2: Explain specifically why it works — what piece becomes active, what threat it creates, "
        "what weakness it exploits — using only CURRENT PIECE LOCATIONS.\n"
        "Sentence 3: Give one forward-looking tip about the next idea in the position using the engine continuation.\n\n"

        "SITUATION F — ⚠️ ILLEGAL MOVE ALERT ⚠️ is in CONTEXT:\n"
        "This means the move has been verified by python-chess as NOT in the legal move list. "
        "It is 100% illegal regardless of how it looks. "
        "MANDATORY: Your FIRST sentence must be exactly: 'That move is illegal.' "
        "Then use CURRENT PIECE LOCATIONS to explain the specific reason (wrong piece geometry, empty square, no such piece on that file, etc.). "
        "DO NOT say the move sounds reasonable. DO NOT describe what it would accomplish. "
        "DO NOT second-guess the illegality check — if CONTEXT says ILLEGAL MOVE ALERT, it IS illegal.\n\n"

        "=== HOW TO PICK THE RIGHT SITUATION ===\n"
        "Check the STOCKFISH VERDICT section of CONTEXT first.\n"
        "If it says NONE, there is no specific move to analyze — use SITUATION D.\n"
        "If it says ⚠️ ILLEGAL MOVE ALERT ⚠️ — ALWAYS use SITUATION F, no exceptions.\n"
        "If it says INACCURACY, MISTAKE, or BLUNDER — check the conversation log.\n"
        "If the last coach message (in conversation history) ended with a question — "
        "compare the student's current message to the COACH EYES ONLY punishment move. "
        "If they match or describe the same piece/move correctly, use SITUATION B. "
        "If they do not match, use SITUATION C.\n"
        "If there is no previous question from the coach, use SITUATION A.\n"
        "If the student's move is STRONG or REASONABLE, use SITUATION E.\n"
    )

    try:
        messages = [{"role": "system", "content": coach_system_prompt}]

        for entry in conversation_log:
            messages.append({"role": entry["role"], "content": entry["content"]})

        messages.append({
            "role": "user",
            "content": f"CONTEXT:\n{context_block}\n\nSTUDENT'S MESSAGE:\n{user_question}"
        })

        response = client.chat.completions.create(
            model=DEFAULT_CHAT_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=300
        )
        answer = response.choices[0].message.content
        return jsonify({"status": "success", "answer": answer})
    except Exception as e:
        print(f"!!! ASK COACH ERROR: {e}")
        return jsonify({"status": "error", "message": "Coach is unavailable right now."})


@app.route('/takeback', methods=['POST'])
def takeback():
    global board
    data = request.json or {}
    moves_to_pop = data.get('moves_to_pop', 2)
    fen = data.get('fen')
    history = data.get('history', [])

    try:
        if history:
            board = chess.Board()
            for san in history:
                move = board.parse_san(san)
                board.push(move)
        elif fen:
            board = chess.Board(fen)

        popped = 0
        for _ in range(moves_to_pop):
            if len(board.move_stack) > 0:
                board.pop()
                popped += 1

        evaluation = get_evaluation(board.fen()) if popped > 0 else 0
        return jsonify({
            "status": "success",
            "fen": board.fen(),
            "popped": popped,
            "evaluation": evaluation
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


if __name__ == '__main__':
    app.run(debug=True)