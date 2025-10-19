from constraint import Problem
from collections import defaultdict
import re, pathlib, sys

DATA_PATH = "ClassTT_01_tiny.txt"

# ---- Universo de tempo ----
DAYS = ["Mon","Tue","Wed","Thu","Fri"]   # 5 dias
BLOCKS_PER_DAY = 4                       # 4 blocos/dia
SLOTS = list(range(1, 5*BLOCKS_PER_DAY + 1))  # 1..20

def slot_day(slot: int) -> str:
    return DAYS[(slot-1)//BLOCKS_PER_DAY]

# ---- Leitura/parse do dataset ----
def read_section(raw: str, tag: str):
    pat = re.compile(rf"#{tag}[^\n]*\n(.*?)(?=\n#|$)", re.S)
    m = pat.search(raw)
    return [] if not m else [ln.strip() for ln in m.group(1).strip().splitlines() if ln.strip()]

def load_dataset(path: str):
    raw = pathlib.Path(path).read_text(encoding="utf-8")

    head = read_section(raw, "head")
    cc   = read_section(raw, "cc")   # classe -> UCs
    dsd  = read_section(raw, "dsd")  # docente -> UCs
    tr   = read_section(raw, "tr")   # indisponibilidades por docente (slots)
    rr   = read_section(raw, "rr")   # restrição de sala por UC
    oc   = read_section(raw, "oc")   # aulas online por (UC, índice)

    # Mapas básicos
    class_to_ucs = {}
    for ln in cc:
        parts = ln.split()
        class_to_ucs[parts[0]] = parts[1:]

    teacher_to_ucs = {}
    for ln in dsd:
        parts = ln.split()
        teacher_to_ucs[parts[0]] = parts[1:]

    teacher_unavail = {}
    for ln in tr:
        parts = ln.split()
        teacher_unavail[parts[0]] = set(map(int, parts[1:]))

    uc_room_required = {}
    for ln in rr:
        uc, room = ln.split()
        uc_room_required[uc] = room

    uc_online_idx = defaultdict(set)
    for ln in oc:
        uc, idx = ln.split()
        uc_online_idx[uc].add(int(idx))

    # Derivados
    uc_to_class = {}
    for c, ucs in class_to_ucs.items():
        for uc in ucs:
            uc_to_class[uc] = c

    uc_to_teacher = {}
    for t, ucs in teacher_to_ucs.items():
        for uc in ucs:
            uc_to_teacher[uc] = t

    UCs = sorted(uc_to_class.keys())

    return {
        "class_to_ucs": class_to_ucs,
        "teacher_to_ucs": teacher_to_ucs,
        "teacher_unavail": teacher_unavail,
        "uc_room_required": uc_room_required,
        "uc_online_idx": uc_online_idx,
        "uc_to_class": uc_to_class,
        "uc_to_teacher": uc_to_teacher,
        "UCs": UCs
    }

# ---- Construção do problema CSP ----
def build_problem(data):
    problem = Problem()

    uc_to_class    = data["uc_to_class"]
    uc_to_teacher  = data["uc_to_teacher"]
    uc_room_req    = data["uc_room_required"]
    teacher_unav   = data["teacher_unavail"]
    uc_online_idx  = data["uc_online_idx"]
    UCs            = data["UCs"]

    # Salas base (ajusta se necessário)
    ROOMS = {"Lab01", "SalaA", "SalaB"}

    variables = []
    by_teacher, by_class = defaultdict(list), defaultdict(list)

    # Neste dataset: 2 aulas/semana por UC
    for uc in UCs:
        for i in (1, 2):
            var = f"{uc}_{i}"
            variables.append(var)

            teacher = uc_to_teacher[uc]
            bad = teacher_unav.get(teacher, set())
            valid_slots = [s for s in SLOTS if s not in bad]

            # modo (online/presencial)
            is_online = i in uc_online_idx.get(uc, set())
            mode = "online" if is_online else "presencial"

            # salas
            if uc in uc_room_req:
                rooms = [uc_room_req[uc]]
            else:
                rooms = sorted(ROOMS)

            domain = [(s, r, mode) for s in valid_slots for r in rooms]
            problem.addVariable(var, domain)

            by_teacher[teacher].append(var)
            by_class[uc_to_class[uc]].append(var)

    # ---- Restrições ----

    # 1 Sala: não pode existir dois eventos com MESMO slot e MESMA sala
    def different_room_or_slot(a, b):
        (sa, ra, _), (sb, rb, _) = a, b
        return not (sa == sb and ra == rb)

    for i in range(len(variables)):
        for j in range(i+1, len(variables)):
            problem.addConstraint(different_room_or_slot, (variables[i], variables[j]))

    # 2 Docente e Turma: não podem dar/ter duas aulas no mesmo slot
    def no_overlap(*vals):
        slots = [v[0] for v in vals]
        return len(slots) == len(set(slots))

    for tvars in by_teacher.values():
        problem.addConstraint(no_overlap, tuple(tvars))
    for cvars in by_class.values():
        problem.addConstraint(no_overlap, tuple(cvars))

    # 3 Máx. 3 aulas por dia por turma
    def max3_por_dia(*vals):
        counts = defaultdict(int)
        for (slot, _, _) in vals:
            counts[slot_day(slot)] += 1
        return all(v <= 3 for v in counts.values())

    for cvars in by_class.values():
        problem.addConstraint(max3_por_dia, tuple(cvars))

    # 4 (Opcional/desafio) Aulas online do mesmo curso no mesmo dia
    def online_same_day(v1, v2):
        (s1, _, m1) = v1
        (s2, _, m2) = v2
        if m1 == "online" and m2 == "online":
            return slot_day(s1) == slot_day(s2)
        return True

    for uc in UCs:
        v1, v2 = f"{uc}_1", f"{uc}_2"
        problem.addConstraint(online_same_day, (v1, v2))

    return problem, by_class, data

# ---- Função de score (soft constraints) ----
def score_solution(sol, by_class, data):
    score = 0
    UCs = data["UCs"]

    # 1 Aulas da mesma UC em dias distintos
    for uc in UCs:
        d1 = slot_day(sol[f"{uc}_1"][0])
        d2 = slot_day(sol[f"{uc}_2"][0])
        if d1 != d2:
            score += 1

    # 2 Aulas consecutivas no mesmo dia (por turma)
    for turma, tvars in by_class.items():
        byday = defaultdict(list)
        for v in tvars:
            byday[slot_day(sol[v][0])].append(sol[v][0])
        for slots in byday.values():
            slots.sort()
            for a, b in zip(slots, slots[1:]):
                if b == a + 1:
                    score += 1

    # 3 Penalizar >4 dias ativos por turma
    for turma, tvars in by_class.items():
        days_used = {slot_day(sol[v][0]) for v in tvars}
        extra = max(0, len(days_used) - 4)
        score -= 2 * extra

    return score

# ---- Impressão legível ----
def show_by_class(sol, by_class):
    print("\n== HORÁRIO POR TURMA ==")
    for turma, tvars in by_class.items():
        print(f"\nTURMA {turma}")
        grid = defaultdict(list)
        for v in tvars:
            slot, room, mode = sol[v]
            uc = v.split("_")[0]
            grid[slot_day(slot)].append((slot, uc, room, mode))
        for d in DAYS:
            row = sorted(grid[d])
            if row:
                print(d, "→", ", ".join([f"{s}: {uc} @{room} ({mode})" for (s, uc, room, mode) in row]))

def show_by_teacher(sol, data):
    print("\n== HORÁRIO POR DOCENTE ==")
    uc_to_teacher = data["uc_to_teacher"]
    teacher_vars = defaultdict(list)
    for var, (slot, room, mode) in sol.items():
        uc = var.split("_")[0]
        t = uc_to_teacher[uc]
        teacher_vars[t].append((slot, uc, room, mode))
    for t, items in teacher_vars.items():
        print(f"\nDOCENTE {t}")
        byday = defaultdict(list)
        for slot, uc, room, mode in items:
            byday[slot_day(slot)].append((slot, uc, room, mode))
        for d in DAYS:
            row = sorted(byday[d])
            if row:
                print(d, "→", ", ".join([f"{s}: {uc} @{room} ({mode})" for (s, uc, room, mode) in row]))

def main():
    try:
        data = load_dataset(DATA_PATH)
    except FileNotFoundError:
        print(f"Erro: não encontrei '{DATA_PATH}'. Coloca o ficheiro ao lado do main.py.")
        sys.exit(1)

    problem, by_class, data = build_problem(data)
    solutions = problem.getSolutions()
    print("Soluções viáveis:", len(solutions))

    if not solutions:
        print("Nenhuma solução encontrada. Verifica restrições e dados.")
        sys.exit(0)

    # Escolher melhor segundo o score
    best = None
    best_score = -10**9
    for sol in solutions:
        sc = score_solution(sol, by_class, data)
        if sc > best_score:
            best, best_score = sol, sc

    print("\n== MELHOR SOLUÇÃO ==")
    print("Score:", best_score)
    show_by_class(best, by_class)
    show_by_teacher(best, data)

if __name__ == "__main__":
    main()
