from constraint import Problem  # pyright: ignore[reportMissingImports]
from collections import defaultdict
import re, pathlib, sys, time, signal

DATA_PATH = "ClassTT_01_tiny.txt"

# ---- Universo de tempo ----
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]   # 5 dias
BLOCKS_PER_DAY = 4                           # 4 blocos/dia
SLOTS = list(range(1, 5 * BLOCKS_PER_DAY + 1))  # 1..20

def slot_day(slot: int) -> str:
    return DAYS[(slot - 1) // BLOCKS_PER_DAY]

# ---- Leitura/parse do dataset ----
def read_section(raw: str, tag: str):
    pat = re.compile(rf"#{tag}[^\n]\n(.?)(?=\n#|$)", re.S)
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

# ---------- DIAGNÓSTICO ----------
def print_dataset_snapshot(data):
    print("\n[SNAPSHOT DATA]")
    print(" - UCs:", len(data["UCs"]))
    print(" - Turmas:", len(set(data["uc_to_class"].values())))
    print(" - Docentes:", len(data["teacher_to_ucs"]))
    for t, ucs in data["teacher_to_ucs"].items():
        print(f"   Docente {t}: UCs={ucs} | indisponíveis={sorted(data['teacher_unavail'].get(t, set()))}")

def compute_var_infos(data, base_rooms=("SalaA","SalaB"), split_week=False):
    uc_to_class    = data["uc_to_class"]
    uc_to_teacher  = data["uc_to_teacher"]
    uc_room_req    = data["uc_room_required"]
    teacher_unav   = data["teacher_unavail"]
    uc_online_idx  = data["uc_online_idx"]
    UCs            = data["UCs"]

    var_infos = []
    for uc in UCs:
        for i in (1, 2):
            name = f"{uc}_{i}"
            teacher = uc_to_teacher[uc]
            turma = uc_to_class[uc]
            bad = teacher_unav.get(teacher, set())
            valid_slots = [s for s in SLOTS if s not in bad]

            if split_week:
                mid = len(SLOTS) // 2
                pivot = SLOTS[mid-1]
                if i == 1:
                    valid_slots = [s for s in valid_slots if s <= pivot]
                else:
                    valid_slots = [s for s in valid_slots if s > pivot]

            is_online = i in uc_online_idx.get(uc, set())
            mode = "online" if is_online else "presencial"

            if is_online:
                rooms = [f"Online::{uc}"]
            else:
                rooms = [uc_room_req[uc]] if uc in uc_room_req else list(base_rooms)

            domain = [(s, r, mode) for s in sorted(valid_slots) for r in sorted(rooms)]
            var_infos.append({
                "name": name,
                "mode": mode,
                "teacher": teacher,
                "turma": turma,
                "valid_slots": sorted(valid_slots),
                "rooms": rooms,
                "domain_size": len(domain),
                "sample": domain[:min(5, len(domain))]
            })
    return var_infos

def run_diagnostics(data):
    print_dataset_snapshot(data)
    var_infos = compute_var_infos(data)
    zeros = [v for v in var_infos if v["domain_size"] == 0]

    print("\n[DOMÍNIOS POR VARIÁVEL]")
    for v in var_infos:
        print(f" - {v['name']:>10} | {v['mode']:<11} | docente={v['teacher']:<8} turma={v['turma']:<8} | slots={len(v['valid_slots']):2d} | salas={len(v['rooms'])} | domínio={v['domain_size']:3d}")
        if v["domain_size"] <= 5:
            print(f"     amostra: {v['sample']}")

    if zeros:
        print("\n[ERRO] Variáveis com domínio ZERO:")
        for v in zeros:
            print(f" - {v['name']} (docente={v['teacher']}, turma={v['turma']}, mode={v['mode']})")
        print("=> Isto torna o problema inviável. Revê indisponibilidades (tr) e salas obrigatórias (rr).")

    # Capacidade docente/turma
    t_to_slots, t_to_cnt = defaultdict(set), defaultdict(int)
    c_to_slots, c_to_cnt = defaultdict(set), defaultdict(int)
    for v in var_infos:
        t_to_slots[v["teacher"]].update(v["valid_slots"])
        t_to_cnt[v["teacher"]] += 1
        c_to_slots[v["turma"]].update(v["valid_slots"])
        c_to_cnt[v["turma"]] += 1

    print("\n[CAPACIDADE POR DOCENTE]")
    for t in sorted(t_to_cnt.keys()):
        print(f" - {t:>8}: aulas={t_to_cnt[t]:2d} | slots livres distintos={len(t_to_slots[t]):2d} | OK? {len(t_to_slots[t]) >= t_to_cnt[t]}")

    print("\n[CAPACIDADE POR TURMA]")
    for c in sorted(c_to_cnt.keys()):
        print(f" - {c:>8}: aulas={c_to_cnt[c]:2d} | slots livres distintos={len(c_to_slots[c]):2d} | OK? {len(c_to_slots[c]) >= c_to_cnt[c]}")

    print("\n[FIM DIAGNÓSTICO]\n")

# ---- Construção do problema CSP (com MRV e opções) ----
def build_problem(data,
                  enforce_online_same_day=True,
                  enforce_max3_per_day=True,
                  base_rooms=("SalaA", "SalaB"),
                  split_week=False,
                  test_ignore_rooms=False,
                  test_ignore_max3=False):
    """
    split_week: força _1 a usar 1ª metade dos slots e _2 a 2ª metade (quebra simetria forte).
    test_ignore_rooms: ignora colisão de sala+slot (para testar viabilidade sem salas).
    test_ignore_max3: ignora 'máx. 3 por dia' (para testar viabilidade sem essa hard).
    """
    uc_to_class    = data["uc_to_class"]
    uc_to_teacher  = data["uc_to_teacher"]
    uc_room_req    = data["uc_room_required"]
    teacher_unav   = data["teacher_unavail"]
    uc_online_idx  = data["uc_online_idx"]
    UCs            = data["UCs"]

    # Pré-computa domínios (para MRV) e valida capacidade mínima
    var_infos = []
    for uc in UCs:
        for i in (1, 2):
            name = f"{uc}_{i}"
            teacher = uc_to_teacher[uc]
            turma = uc_to_class[uc]
            bad = teacher_unav.get(teacher, set())
            valid_slots = [s for s in SLOTS if s not in bad]

            if split_week:
                mid = len(SLOTS) // 2
                pivot = SLOTS[mid-1]
                if i == 1:
                    valid_slots = [s for s in valid_slots if s <= pivot]
                else:
                    valid_slots = [s for s in valid_slots if s > pivot]

            is_online = i in uc_online_idx.get(uc, set())
            mode = "online" if is_online else "presencial"

            if is_online:
                rooms = [f"Online::{uc}"]
            else:
                rooms = [uc_room_req[uc]] if uc in uc_room_req else list(base_rooms)

            domain = [(s, r, mode) for s in sorted(valid_slots) for r in sorted(rooms)]
            var_infos.append({
                "name": name,
                "domain": domain,
                "mode": mode,
                "teacher": teacher,
                "turma": turma,
                "inperson": (mode == "presencial"),
                "valid_slots_only": set(valid_slots)
            })

    zeros = [vi for vi in var_infos if len(vi["domain"]) == 0]
    if zeros:
        print("\n[ERRO] Algumas variáveis ficaram com domínio vazio:")
        for vi in zeros:
            print(f" - {vi['name']} (teacher={vi['teacher']}, turma={vi['turma']}, mode={vi['mode']})")
        print("Revê indisponibilidades (tr) e restrições de sala (rr).")
        return None, None, None

    teacher_to_vars = defaultdict(list)
    class_to_vars = defaultdict(list)
    for vi in var_infos:
        teacher_to_vars[vi["teacher"]].append(vi)
        class_to_vars[vi["turma"]].append(vi)

    # Checks de capacidade mínima
    for t, vs in teacher_to_vars.items():
        union = set()
        for vi in vs:
            union |= vi["valid_slots_only"]
        if len(union) < len(vs):
            print(f"\n[ERRO] Docente {t} tem {len(vs)} aulas mas apenas {len(union)} slots livres possíveis (inviável).")
            return None, None, None

    for c, vs in class_to_vars.items():
        union = set()
        for vi in vs:
            union |= vi["valid_slots_only"]
        if len(union) < len(vs):
            print(f"\n[ERRO] Turma {c} tem {len(vs)} aulas mas apenas {len(union)} slots livres possíveis (inviável).")
            return None, None, None

    # Cria o solver e adiciona variáveis em ordem MRV
    problem = Problem()

    var_infos.sort(key=lambda x: len(x["domain"]))  # MRV
    inperson_vars = []
    for vi in var_infos:
        problem.addVariable(vi["name"], vi["domain"])
        if vi["inperson"]:
            inperson_vars.append(vi["name"])

    # ---- Restrições ----

    # (A) Sala+slot únicos (global) só para presenciais
    def proj_slot_sala(*vals):
        return len({(s, r) for (s, r, m) in vals}) == len(vals)
    if inperson_vars and (not test_ignore_rooms):
        problem.addConstraint(proj_slot_sala, tuple(inperson_vars))

    # (B) Docente: não pode dar 2 aulas no mesmo slot
    def no_overlap(*vals):
        slots = [v[0] for v in vals]
        return len(slots) == len(set(slots))
    for t, vs in teacher_to_vars.items():
        problem.addConstraint(no_overlap, tuple(v["name"] for v in vs))

    # (C) Turma: não pode ter 2 aulas no mesmo slot
    for c, vs in class_to_vars.items():
        problem.addConstraint(no_overlap, tuple(v["name"] for v in vs))

    # (D) Máx. 3 aulas por dia por turma (hard, se não estiver em modo de teste)
    if enforce_max3_per_day and (not test_ignore_max3):
        def max3_por_dia(*vals):
            counts = defaultdict(int)
            for (slot, _, _) in vals:
                counts[slot_day(slot)] += 1
            return all(v <= 3 for v in counts.values())
        for c, vs in class_to_vars.items():
            problem.addConstraint(max3_por_dia, tuple(v["name"] for v in vs))

    # (E) Online mesmo dia (opcional)
    def online_same_day(v1, v2):
        (s1, _, m1) = v1
        (s2, _, m2) = v2
        if m1 == "online" and m2 == "online":
            return slot_day(s1) == slot_day(s2)
        return True

    # (F) Quebra de simetria: _1 antes de _2
    def order(a, b):
        return a[0] < b[0]

    UCs = data["UCs"]
    for uc in UCs:
        v1, v2 = f"{uc}_1", f"{uc}_2"
        if enforce_online_same_day:
            problem.addConstraint(online_same_day, (v1, v2))
        problem.addConstraint(order, (v1, v2))

    # Estrutura por turma para scoring/impressão
    by_class = defaultdict(list)
    for vi in var_infos:
        by_class[vi["turma"]].append(vi["name"])

    return problem, by_class, data

# ---- Função de score (soft constraints) ----
def score_solution(sol, by_class, data, soft_max3=True):
    score = 0
    UCs = data["UCs"]

    # 1) Aulas da mesma UC em dias distintos
    for uc in UCs:
        d1 = slot_day(sol[f"{uc}_1"][0])
        d2 = slot_day(sol[f"{uc}_2"][0])
        if d1 != d2:
            score += 1

    # 2) Aulas consecutivas no mesmo dia (por turma)
    for turma, tvars in by_class.items():
        byday = defaultdict(list)
        for v in tvars:
            byday[slot_day(sol[v][0])].append(sol[v][0])
        for slots in byday.values():
            slots.sort()
            for a, b in zip(slots, slots[1:]):
                if b == a + 1:
                    score += 1

    # 3) Penalizar >4 dias ativos por turma
    for turma, tvars in by_class.items():
        days_used = {slot_day(sol[v][0]) for v in tvars}
        extra = max(0, len(days_used) - 4)
        score -= 2 * extra

    # 4) Se “max3 por dia” for soft neste modelo, penaliza excesso
    if soft_max3:
        for turma, tvars in by_class.items():
            counts = defaultdict(int)
            for v in tvars:
                counts[slot_day(sol[v][0])] += 1
            for c in counts.values():
                if c > 3:
                    score -= (c - 3)

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

# ---- Timeout utilitário (Unix-like) ----
class Timeout(Exception): pass

def _handle_timeout(signum, frame):
    raise Timeout()

def run_with_timeout(fn, seconds):
    old = signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(max(1, int(seconds)))
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)

# ---- Estratégia em cascata com time budget ----
def try_solve_with_budget(data, total_seconds=60.0):
    """
    Várias tentativas com restrições diferentes e timeout.
    Devolve (solucao, by_class, soft_max3).
    """
    layers = [
        ("Modelo completo",
         dict(enforce_online_same_day=True,  enforce_max3_per_day=True,  base_rooms=("SalaA","SalaB"), split_week=False, test_ignore_rooms=False, test_ignore_max3=False),
         False),
        ("Sem online_same_day",
         dict(enforce_online_same_day=False, enforce_max3_per_day=True,  base_rooms=("SalaA","SalaB"), split_week=False, test_ignore_rooms=False, test_ignore_max3=False),
         False),
        ("Menos salas (1 sala base)",
         dict(enforce_online_same_day=False, enforce_max3_per_day=True,  base_rooms=("SalaA",),       split_week=False, test_ignore_rooms=False, test_ignore_max3=False),
         False),
        ("Split semana (_1 1ª metade; _2 2ª)",
         dict(enforce_online_same_day=False, enforce_max3_per_day=True,  base_rooms=("SalaA",),       split_week=True,  test_ignore_rooms=False, test_ignore_max3=False),
         False),
        ("Sem max3_por_dia como hard (fica soft)",
         dict(enforce_online_same_day=False, enforce_max3_per_day=False, base_rooms=("SalaA",),       split_week=True,  test_ignore_rooms=False, test_ignore_max3=False),
         True),
        ("TESTE: ignorar rooms e max3 (viabilidade estrutural)",
         dict(enforce_online_same_day=False, enforce_max3_per_day=False, base_rooms=("SalaA","SalaB"), split_week=False, test_ignore_rooms=True,  test_ignore_max3=True),
         True),
    ]

    per_try = max(1.5, total_seconds / len(layers))

    for desc, kwargs, soft_max3 in layers:
        print(f"\n[TRY] {desc} (timeout ~{per_try:.1f}s)")
        build = build_problem(data, **kwargs)
        if build == (None, None, None):
            print(" - Este nível está inviável à partida (domínios a 0 ou capacidade insuficiente).")
            continue

        problem, by_class, _ = build

        # 1) tenta 1.ª solução rápida
        start = time.time()
        try:
            sol = run_with_timeout(problem.getSolution, per_try)
        except Timeout:
            print(" - Timeout nesta tentativa (sem 1.ª solução).")
            sol = None

        if not sol:
            continue

        # 2) polimento com tempo residual
        leftover = max(0.0, per_try - (time.time() - start))
        best, best_score = sol, score_solution(sol, by_class, data, soft_max3=soft_max3)
        if leftover >= 0.5:
            def improve():
                nonlocal best, best_score
                deadline = time.time() + leftover
                for s in problem.getSolutionIter():
                    sc = score_solution(s, by_class, data, soft_max3=soft_max3)
                    if sc > best_score:
                        best, best_score = s, sc
                    if time.time() > deadline:
                        break
                return best, best_score
            try:
                best, best_score = run_with_timeout(improve, leftover)
                print(f" - Polido; melhor score={best_score}.")
            except Timeout:
                print(f" - Polido até ao limite; melhor score={best_score}.")

        return best, by_class, soft_max3

    return None, None, False

# ---- MAIN ----
def main():
    try:
        data = load_dataset(DATA_PATH)
    except FileNotFoundError:
        print(f"Erro: não encontrei '{DATA_PATH}'. Coloca o ficheiro ao lado do main.py.")
        sys.exit(1)

    print("A correr diagnóstico rápido...")
    run_diagnostics(data)

    print("A procurar soluções com orçamento de tempo...")
    TOTAL_SECONDS = 60.0  # ajusta conforme precisares
    sol, by_class, soft_max3 = try_solve_with_budget(data, total_seconds=TOTAL_SECONDS)

    if not sol:
        print("\nNenhuma solução encontrada dentro do orçamento de tempo.")
        print("DICAS: ")
        print(" - Se o 'TESTE: ignorar rooms e max3' ENCONTRAR solução → o problema está nas salas/limite diário.")
        print(" - Se NEM o teste encontrar solução → conflito nas indisponibilidades ou carga por docente/turma.")
        print(" - Vê o diagnóstico acima (domínios zero e 'OK? False').")
        sys.exit(0)

    sc = score_solution(sol, by_class, data, soft_max3=soft_max3)
    print("\n== MELHOR SOLUÇÃO ENCONTRADA DENTRO DO TEMPO ==")
    print("Score:", sc)
    show_by_class(sol, by_class)
    show_by_teacher(sol, data)

if _name_ == "_main_":
    # Timeout via signal funciona em macOS/Linux. Usa: python -u main.py
    main()