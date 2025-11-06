# =============================================================================
#  IA25_P01_G02 — Gerador de Horários com CSP (com exportação colorida + banner)
#
#  O que faz:
#   1) Lê o ficheiro ClassTT_01_tiny.txt (turmas, docentes, indisponibilidades, etc.)
#   2) Valida e faz diagnóstico (domínios, capacidade mínima)
#   3) Constrói um CSP (python-constraint) e procura a 1.ª solução viável
#   4) Mostra horários por turma e por docente
#   5) Exporta para CSV, PNG e PDF (cores por UC, hatch em aulas online)
#   6) Coloca um banner docs/banner.png no topo dos PNG/PDF
#
#   Alunos: Grupo II - António Ferreira, Mafalda Barão, Gonçalo Gomes, Ruben Dias, João Morais
# =============================================================================

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple
import re, pathlib, sys, time, platform, os, colorsys, hashlib


from constraint import Problem, MinConflictsSolver  
import pandas as pd
import matplotlib.pyplot as plt



# 1) CONFIGURAÇÃO 


DATA_PATH = "ClassTT_01_tiny.txt"  # ficheiro do dataset

# Universo temporal: 5 dias * 4 blocos (2h cada) => 20 slots numerados 1..20
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
BLOCKS_PER_DAY = 4
SLOTS = list(range(1, 5 * BLOCKS_PER_DAY + 1))  # [1..20]

# Tags de blocos e horários disponiveis
BLOCK_LABELS = ["B1", "B2", "B3", "B4"]
BLOCK_TO_TIME = {
    "B1": "09:00–11:00",
    "B2": "11:00–13:00",
    "B3": "14:00–16:00",
    "B4": "16:00–18:00",
}



# 2) FUNÇÕES 


def slot_day(slot: int) -> str:
    """Converte slot (1..20) no dia ('Mon'..'Fri')."""
    return DAYS[(slot - 1) // BLOCKS_PER_DAY]

def slot_to_day_and_block(slot: int) -> Tuple[str, str]:
    """Converte slot (1..20) em (dia, bloco: B1..B4)."""
    day_idx = (slot - 1) // BLOCKS_PER_DAY
    block_idx = (slot - 1) % BLOCKS_PER_DAY
    return DAYS[day_idx], BLOCK_LABELS[block_idx]

def read_section(raw: str, tag: str) -> List[str]:
    pat = re.compile(rf"#{tag}[^\n]*\n(.*?)(?=\n#|$)", re.S)
    m = pat.search(raw)
    return [] if not m else [ln.strip() for ln in m.group(1).strip().splitlines() if ln.strip()]



# 3) LEITURA DO DATASET

def load_dataset(path: str) -> Dict:
    """
    Lê o ficheiro e constrói mapas base e derivados:
      - class_to_ucs: turma -> [UCs]
      - teacher_to_ucs: docente -> [UCs]
      - teacher_unavail: docente -> set(slots indisponíveis)
      - uc_room_required: UC -> sala obrigatória
      - uc_online_idx: UC -> set({1,2}) índices de aulas online
      - uc_to_class / uc_to_teacher
      - UCs: lista de todas as UCs (ordenada)
    """
    raw = pathlib.Path(path).read_text(encoding="utf-8")

    cc   = read_section(raw, "cc")
    dsd  = read_section(raw, "dsd")
    tr   = read_section(raw, "tr")
    rr   = read_section(raw, "rr")
    oc   = read_section(raw, "oc")

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
        # cada linha deve ter 2 tokens (UC e índice 1/2)
        uc, idx = ln.split()
        uc_online_idx[uc].add(int(idx))

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



# 4) VALIDAÇÃO E DIAGNÓSTICO INICIAL


def sanity_check_data(data: Dict) -> bool:
    """Verifica: UC tem turma/docente; slots de indisponibilidade estão em 1..20; salas obrigatórias válidas."""
    ok = True
    UCs = data["UCs"]
    uc_to_class   = data["uc_to_class"]
    uc_to_teacher = data["uc_to_teacher"]
    teacher_unav  = data["teacher_unavail"]

    for uc in UCs:
        if uc not in uc_to_class:
            print(f"[SANITY] UC sem turma: {uc}"); ok = False
        if uc not in uc_to_teacher:
            print(f"[SANITY] UC sem docente: {uc}"); ok = False

    for t, ss in teacher_unav.items():
        for s in ss:
            if s not in SLOTS:
                print(f"[SANITY] Slot {s} fora do intervalo 1..{len(SLOTS)} (docente {t})")
                ok = False

    for uc, room in data["uc_room_required"].items():
        if not room or not isinstance(room, str):
            print(f"[SANITY] Sala obrigatória inválida em {uc}: {room!r}")
            ok = False

    return ok

def compute_var_infos(data: Dict, base_rooms=("SalaA","SalaB"), split_week=False) -> List[Dict]:
    """
    Para cada UC_i (i=1,2) calcula:
      - modo (online/presencial)
      - slots válidos (após indisponibilidades e split_week)
      - salas possíveis (obrigatória ou base; online usa marcador lógico)
      - tamanho do domínio (cartesiano slots × salas)
    """
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

            # Split semana: 1 na 1.ª metade dos slots; 2 na 2.ª 
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

def print_dataset_snapshot(data: Dict) -> None:
    #Resumo simples do dataset
    print("\n[SNAPSHOT DATA]")
    print(" - UCs:", len(data["UCs"]))
    print(" - Turmas:", len(set(data["uc_to_class"].values())))
    print(" - Docentes:", len(data["teacher_to_ucs"]))
    for t, ucs in data["teacher_to_ucs"].items():
        print(f"   Docente {t}: UCs={ucs} | indisponíveis={sorted(data['teacher_unavail'].get(t, set()))}")

def run_diagnostics(data: Dict) -> None:
    #Mostra domínios por variável e capacidade (slots livres ≥ nº aulas) por docente/turma.
    print_dataset_snapshot(data)
    var_infos = compute_var_infos(data)

    print("\n[DOMÍNIOS POR VARIÁVEL]")
    zeros = []
    for v in var_infos:
        print(f" - {v['name']:>10} | {v['mode']:<11} | docente={v['teacher']:<8} turma={v['turma']:<8} | slots={len(v['valid_slots']):2d} | salas={len(v['rooms'])} | domínio={v['domain_size']:3d}")
        if v["domain_size"] <= 5:
            print(f"     amostra: {v['sample']}")
        if v["domain_size"] == 0:
            zeros.append(v)

    if zeros:
        print("\n[ERRO] Variáveis com domínio ZERO (slot/sala) → inviável.")
        for v in zeros:
            print(f"   - {v['name']} | docente={v['teacher']} turma={v['turma']} mode={v['mode']} | slots={v['valid_slots']} | salas={v['rooms']}")

    # Capacidade mínima por docente/turma
    t_to_slots, t_to_cnt = defaultdict(set), defaultdict(int)
    c_to_slots, c_to_cnt = defaultdict(set), defaultdict(int)
    for v in var_infos:
        t_to_slots[v["teacher"]].update(v["valid_slots"])
        t_to_cnt[v["teacher"]] += 1
        c_to_slots[v["turma"]].update(v["valid_slots"])
        c_to_cnt[v["turma"]] += 1

    print("\n[CAPACIDADE POR DOCENTE]")
    for t in sorted(t_to_cnt.keys()):
        ok = len(t_to_slots[t]) >= t_to_cnt[t]
        print(f" - {t:>8}: aulas={t_to_cnt[t]:2d} | slots_livres={len(t_to_slots[t]):2d} | OK? {ok}")

    print("\n[CAPACIDADE POR TURMA]")
    for c in sorted(c_to_cnt.keys()):
        ok = len(c_to_slots[c]) >= c_to_cnt[c]
        print(f" - {c:>8}: aulas={c_to_cnt[c]:2d} | slots_livres={len(c_to_slots[c]):2d} | OK? {ok}")

    print("\n[FIM DIAGNÓSTICO]\n")


# 5) CONSTRUÇÃO DO PROBLEMA

def build_problem(
    data: Dict,
    enforce_online_same_day=True,   # se as 2 aulas de uma UC forem online, ficam no mesmo dia
    enforce_max3_per_day=True,      # máx. 3 aulas/dia por turma (hard)
    enforce_order=True,             # UC_1 ocorre antes de UC_2
    base_rooms=("SalaA", "SalaB"),  # salas defaut para presenciais
    split_week=False,               # UC_1 em 1.ª metade dos slots; UC_2 em 2.ª
    test_ignore_rooms=False,        # ignora colisões (slot,sala) nas presenciais
    test_ignore_max3=False          # ignora máx. 3/dia
):
    #Constrói variáveis e restrições e devolve (problem, by_class, data)

    uc_to_class    = data["uc_to_class"]
    uc_to_teacher  = data["uc_to_teacher"]
    uc_room_req    = data["uc_room_required"]
    teacher_unav   = data["teacher_unavail"]
    uc_online_idx  = data["uc_online_idx"]
    UCs            = data["UCs"]

    # --- Definição de variáveis + domínios ---
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
                valid_slots = [s for s in valid_slots if s <= pivot] if i == 1 else [s for s in valid_slots if s > pivot]

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

    # Falha imediata se algum domínio for vazio
    zeros = [vi for vi in var_infos if len(vi["domain"]) == 0]
    if zeros:
        print("\n[ERRO] Domínio vazio (inviável):")
        for vi in zeros:
            print(f"   - {vi['name']} (docente={vi['teacher']}, turma={vi['turma']}, mode={vi['mode']})")
        return None, None, None

    # Agrupar por docente e turma
    teacher_to_vars = defaultdict(list)
    class_to_vars = defaultdict(list)
    for vi in var_infos:
        teacher_to_vars[vi["teacher"]].append(vi)
        class_to_vars[vi["turma"]].append(vi)

    # Capacidade mínima: nº de slots livres distintos ≥ nº de aulas
    for t, vs in teacher_to_vars.items():
        union = set().union(*[vi["valid_slots_only"] for vi in vs])
        if len(union) < len(vs):
            print(f"\n[ERRO] Docente {t}: {len(vs)} aulas mas só {len(union)} slots livres.")
            return None, None, None
    for c, vs in class_to_vars.items():
        union = set().union(*[vi["valid_slots_only"] for vi in vs])
        if len(union) < len(vs):
            print(f"\n[ERRO] Turma {c}: {len(vs)} aulas mas só {len(union)} slots livres.")
            return None, None, None

    # --- Criar solver (Min-Conflicts rápido para 1.ª solução) ---
    problem = Problem(MinConflictsSolver(steps=50000))  

    # MRV simples: adicionar variáveis por ordem crescente de tamanho do domínio
    var_infos.sort(key=lambda x: len(x["domain"]))
    inperson_vars = []
    for vi in var_infos:
        problem.addVariable(vi["name"], vi["domain"])
        if vi["inperson"]:
            inperson_vars.append(vi["name"])

    # --- Restrições ---
    # (A) Unicidade do par (slot, sala) nas aulas presenciais
    def proj_slot_sala(*vals):
        return len({(s, r) for (s, r, m) in vals}) == len(vals)
    if inperson_vars and not test_ignore_rooms:
        problem.addConstraint(proj_slot_sala, tuple(inperson_vars))

    # (B) Docente sem sobreposição de slots
    def no_overlap(*vals):
        slots = [v[0] for v in vals]
        return len(slots) == len(set(slots))
    for t, vs in teacher_to_vars.items():
        problem.addConstraint(no_overlap, tuple(v["name"] for v in vs))

    # (C) Turma sem sobreposição de slots
    for c, vs in class_to_vars.items():
        problem.addConstraint(no_overlap, tuple(v["name"] for v in vs))

    # (D) Máx. 3 aulas/dia por turma (se não for teste)
    if enforce_max3_per_day and not test_ignore_max3:
        def max3_por_dia(*vals):
            counts = defaultdict(int)
            for (slot, _, _) in vals:
                counts[slot_day(slot)] += 1
            return all(v <= 3 for v in counts.values())
        for c, vs in class_to_vars.items():
            problem.addConstraint(max3_por_dia, tuple(v["name"] for v in vs))

    # (E) Se as 2 aulas da UC forem online, ficam no mesmo dia
    def online_same_day(v1, v2):
        (s1, _, m1) = v1
        (s2, _, m2) = v2
        if m1 == "online" and m2 == "online":
            return slot_day(s1) == slot_day(s2)
        return True

    # (F) Quebra de simetria: UC_1 antes de UC_2
    def order(a, b):
        return a[0] < b[0]

    UCs = data["UCs"]
    for uc in UCs:
        v1, v2 = f"{uc}_1", f"{uc}_2"
        if enforce_online_same_day:
            problem.addConstraint(online_same_day, (v1, v2))
        if enforce_order:
            problem.addConstraint(order, (v1, v2))

    # Estrutura auxiliar para impressão/exportação
    by_class = defaultdict(list)
    for vi in var_infos:
        by_class[vi["turma"]].append(vi["name"])

    return problem, by_class, data

# 6) PROCURA COM ORÇAMENTO (timeout por camada)

def first_solution_with_deadline(problem: Problem, seconds: float):
    """
    MinConflictsSolver não tem iterador → fazemos várias tentativas (restarts)
    até encontrar 1 solução ou acabar o tempo (deadline).
    """
    deadline = time.monotonic() + max(0.1, float(seconds))
    while time.monotonic() < deadline:
        sol = problem.getSolution()
        if sol is not None:
            return sol
    return None

def try_solve_with_budget(data: Dict, total_seconds=90.0):
    """
    Camadas (do mais permissivo ao completo). Paramos na 1.ª que devolve solução.
    O 'soft_max3' indica se a regra max3 foi tratada como suave nessa camada.
    """
    layers = [
        ("DEBUG: sala/max3/online, com order+split",
         dict(enforce_online_same_day=False, enforce_max3_per_day=False, enforce_order=True,
              base_rooms=("SalaA","SalaB"), split_week=True,
              test_ignore_rooms=True, test_ignore_max3=True),
         True),

        ("TESTE: ignorar rooms e max3",
         dict(enforce_online_same_day=False, enforce_max3_per_day=False, enforce_order=True,
              base_rooms=("SalaA","SalaB"), split_week=False,
              test_ignore_rooms=True, test_ignore_max3=True),
         True),

        ("Sem max3 hard (soft) + split semana",
         dict(enforce_online_same_day=False, enforce_max3_per_day=False, enforce_order=True,
              base_rooms=("SalaA",), split_week=True,
              test_ignore_rooms=False, test_ignore_max3=False),
         True),

        ("Split semana + max3 hard",
         dict(enforce_online_same_day=False, enforce_max3_per_day=True, enforce_order=True,
              base_rooms=("SalaA",), split_week=True,
              test_ignore_rooms=False, test_ignore_max3=False),
         False),

        ("1 sala base + max3 hard",
         dict(enforce_online_same_day=False, enforce_max3_per_day=True, enforce_order=True,
              base_rooms=("SalaA",), split_week=False,
              test_ignore_rooms=False, test_ignore_max3=False),
         False),

        ("Sem online_same_day + max3 hard + 2 salas",
         dict(enforce_online_same_day=False, enforce_max3_per_day=True, enforce_order=True,
              base_rooms=("SalaA","SalaB"), split_week=False,
              test_ignore_rooms=False, test_ignore_max3=False),
         False),

        ("Modelo completo",
         dict(enforce_online_same_day=True, enforce_max3_per_day=True, enforce_order=True,
              base_rooms=("SalaA","SalaB"), split_week=False,
              test_ignore_rooms=False, test_ignore_max3=False),
         False),
    ]

    per_try = max(3.0, total_seconds / len(layers))

    for desc, kwargs, soft_max3 in layers:
        print(f"\n[TRY] {desc} (timeout ~{per_try:.1f}s)")
        build = build_problem(data, **kwargs)
        if build == (None, None, None):
            print(" - Inviável à partida (domínios a 0 / capacidade insuficiente).")
            continue

        problem, by_class, _ = build
        sol = first_solution_with_deadline(problem, per_try)
        if sol is None:
            print(" - Sem 1.ª solução dentro do tempo desta camada.")
            continue

        return sol, by_class, soft_max3

    return None, None, False



# 7) SCORE E DISPLAY


def score_solution(sol: Dict[str, Tuple[int,str,str]], by_class: Dict[str, List[str]], data: Dict, soft_max3=True) -> int:
    """
    Score apenas indicativo:
      + 1 se as aulas de uma UC ficarem em dias distintos
      + 1 por par de blocos consecutivos no mesmo dia (por turma)
      - 2 por cada dia ativo acima de 4 (por turma)
      - (se max3 for soft) -1 por aula acima de 3 num dia (por turma)
    """
    score = 0
    UCs = data["UCs"]

    for uc in UCs:
        d1 = slot_day(sol[f"{uc}_1"][0])
        d2 = slot_day(sol[f"{uc}_2"][0])
        if d1 != d2:
            score += 1

    for turma, tvars in by_class.items():
        byday = defaultdict(list)
        for v in tvars:
            byday[slot_day(sol[v][0])].append(sol[v][0])
        for slots in byday.values():
            slots.sort()
            for a, b in zip(slots, slots[1:]):
                if b == a + 1:
                    score += 1

    for turma, tvars in by_class.items():
        days_used = {slot_day(sol[v][0]) for v in tvars}
        extra = max(0, len(days_used) - 4)
        score -= 2 * extra

    if soft_max3:
        for turma, tvars in by_class.items():
            counts = defaultdict(int)
            for v in tvars:
                counts[slot_day(sol[v][0])] += 1
            for c in counts.values():
                if c > 3:
                    score -= (c - 3)

    return score

def show_by_class(sol: Dict[str, Tuple[int,str,str]], by_class: Dict[str, List[str]]) -> None:
    #Imprime horários por turma em formato humano.
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
                print(d, "→", ", ".join([f"{s}: {uc} @{'ONLINE' if mode=='online' else room} ({mode})" for (s, uc, room, mode) in row]))

def show_by_teacher(sol: Dict[str, Tuple[int,str,str]], data: Dict) -> None:
    #Imprime horários por docente.
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
                print(d, "→", ", ".join([f"{s}: {uc} @{'ONLINE' if mode=='online' else room} ({mode})" for (s, uc, room, mode) in row]))

# 8) EXPORTAÇÃO (CSV, PNG, PDF) COLORIDA

@dataclass
class SlotEntry:
    slot: int
    uc: str
    room: str
    mode: str   # 'presencial' | 'online'

def build_calendar_frames(sol: Dict[str, Tuple[int,str,str]],
                          by_class: Dict[str, List[str]],
                          data: Dict) -> Dict[str, pd.DataFrame]:
    """
    Cria DataFrame por turma:
      linhas = Mon..Fri ; colunas = B1..B4 ; bloco = 'UC @Sala' ou 'UC @ONLINE (online)'
    """
    frames: Dict[str, pd.DataFrame] = {}
    for turma, tvars in by_class.items():
        grid = {blk: {day: "" for day in DAYS} for blk in BLOCK_LABELS}
        for var in tvars:
            uc = var.split("_")[0]
            slot, room, mode = sol[var]
            day, blk = slot_to_day_and_block(slot)
            label = f"{uc} @{'ONLINE' if mode=='online' else room}{' (online)' if mode=='online' else ''}"
            grid[blk][day] = (grid[blk][day] + " | " if grid[blk][day] else "") + label
        df = pd.DataFrame({blk: [grid[blk][d] for d in DAYS] for blk in BLOCK_LABELS}, index=DAYS)
        frames[turma] = df
    return frames

# ---------- Cores por UC ----------

def uc_to_rgb(uc: str) -> Tuple[float,float,float]:
    #Converte o nome da UC numa cor HSV → RGB (mesma UC = mesma cor).
    h = int(hashlib.md5(uc.encode("utf-8")).hexdigest(), 16)
    hue = (h % 360) / 360.0
    sat, val = 0.45, 0.95
    return colorsys.hsv_to_rgb(hue, sat, val)

def luminance(rgb: Tuple[float,float,float]) -> float:
    #Validação da cor para colocar o texto
    r, g, b = rgb
    return 0.2126*r + 0.7152*g + 0.0722*b

def text_color_for_bg(rgb: Tuple[float,float,float]) -> str:
    """Preto em fundos claros; branco em fundos escuros."""
    return "black" if luminance(rgb) > 0.6 else "white"

# ---------- Banner no topo ----------
def _try_load_banner(path="docs/banner.png"):
    """Tenta carregar docs/banner.png; se falhar, devolve None (sem quebrar export)."""
    try:
        import matplotlib.image as mpimg
        if os.path.exists(path):
            return mpimg.imread(path)
    except Exception:
        pass
    return None

def _render_df_as_figure_colored(df: pd.DataFrame, title: str, figsize=(12, 6.2)):
    """
    Desenha a tabela (matplotlib) com:
      - Banner no topo
      - Cabeçalhos com hora por bloco
      - Blocos coloridas por UC; '///' hatch para aulas ONLINE
    """
    import matplotlib.gridspec as gridspec

    fig = plt.figure(figsize=figsize, dpi=160)
    gs = gridspec.GridSpec(nrows=2, ncols=1, height_ratios=[0.30, 0.70], figure=fig)

    # (1) Banner / Título
    ax_banner = fig.add_subplot(gs[0])
    ax_banner.axis("off")
    banner = _try_load_banner("docs/banner.png")
    if banner is not None:
        ax_banner.imshow(banner)
        ax_banner.set_title(title, fontsize=16, fontweight="bold", pad=6)
    else:
        ax_banner.text(0.5, 0.5, title, ha="center", va="center",
                       fontsize=16, fontweight="bold")

    # (2) Tabela
    ax = fig.add_subplot(gs[1])
    ax.axis("off")

    cell_text = df.values
    row_labels = [f"{d}" for d in df.index]
    col_labels = [f"{c}\n{BLOCK_TO_TIME[c]}" for c in df.columns]

    tbl = ax.table(cellText=cell_text,
                   rowLabels=row_labels,
                   colLabels=col_labels,
                   loc="center",
                   cellLoc="center")

    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1.1, 1.6)

    # Estilo de cabeçalhos
    for (i, j), cell in tbl.get_celld().items():
        if i == 0:
            cell.set_text_props(fontweight='bold')
            cell.set_facecolor((0.92, 0.92, 0.95))
        if j == -1:
            cell.set_text_props(fontweight='bold')
            cell.set_facecolor((0.92, 0.92, 0.95))

    # Pintar blocos por UC
    n_rows, n_cols = df.shape
    for ridx in range(n_rows):
        for cidx in range(n_cols):
            cell = tbl[ridx+1, cidx]  # +1 = cabeçalho de linha
            txt = df.iat[ridx, cidx]
            if not txt:
                cell.set_facecolor((1, 1, 1))
                continue

            parts = [p.strip() for p in txt.split("|")]  # proteção a múltiplas aulas na mesma blocos
            if len(parts) == 1:
                uc = parts[0].split()[0]           
                bg = uc_to_rgb(uc)
                cell.set_facecolor(bg)
                cell.get_text().set_color(text_color_for_bg(bg))
                if "@ONLINE" in parts[0]:
                    cell.set_hatch("///")          
            else:
                # Caso raro: duas aulas no mesmo bloco
                cell.set_facecolor((0.85, 0.85, 0.85))
                cell.get_text().set_color("black")

    fig.tight_layout()
    return fig

# ---------- Exportação ----------

def export_csv(frames: Dict[str, pd.DataFrame], outdir: str) -> None:
    #Exporta CSV por turma + CSV agregado (todas as turmas).
    os.makedirs(outdir, exist_ok=True)
    for turma, df in frames.items():
        df.to_csv(os.path.join(outdir, f"horario_{turma}.csv"), encoding="utf-8")

    # CSV agregado
    rows = []
    for turma, df in frames.items():
        for day in df.index:
            for blk in df.columns:
                rows.append({
                    "turma": turma,
                    "dia": day,
                    "bloco": blk,
                    "hora": BLOCK_TO_TIME[blk],
                    "aula": df.loc[day, blk],
                })
    pd.DataFrame(rows).to_csv(os.path.join(outdir, "horarios_todos.csv"), index=False, encoding="utf-8")

def export_images(frames: Dict[str, pd.DataFrame], outdir: str) -> None:
    #Exporta PNG colorido por turma com banner.
    os.makedirs(outdir, exist_ok=True)
    for turma, df in frames.items():
        fig = _render_df_as_figure_colored(df, f"Horário {turma}")
        fig.savefig(os.path.join(outdir, f"horario_{turma}.png"), bbox_inches="tight")
        plt.close(fig)

def export_pdfs(frames: Dict[str, pd.DataFrame], outdir: str) -> None:
    #Exporta PDF colorido por turma banner.
    os.makedirs(outdir, exist_ok=True)
    for turma, df in frames.items():
        fig = _render_df_as_figure_colored(df, f"Horário {turma}")
        fig.savefig(os.path.join(outdir, f"horario_{turma}.pdf"), bbox_inches="tight")
        plt.close(fig)

def export_all(sol, by_class, data, outdir="export") -> None:
    #Pipeline completo de exportação.
    frames = build_calendar_frames(sol, by_class, data)
    export_csv(frames, os.path.join(outdir, "csv"))
    export_images(frames, os.path.join(outdir, "img"))
    export_pdfs(frames, os.path.join(outdir, "pdf"))
    print(f"\n[EXPORT] CSV → {os.path.join(outdir, 'csv')}")
    print(f"[EXPORT] PNG → {os.path.join(outdir, 'img')}")
    print(f"[EXPORT] PDF → {os.path.join(outdir, 'pdf')}")


# 9) MAIN

def main():
    # 1) Ler dataset
    try:
        data = load_dataset(DATA_PATH)
    except FileNotFoundError:
        print(f"Erro: não encontrei '{DATA_PATH}'. Coloca o ficheiro ao lado do main.py.")
        sys.exit(1)

    # 2) Validação minima
    if not sanity_check_data(data):
        print("Erros de consistência no dataset. Corrige antes de continuar.")
        sys.exit(1)

    # 3) Diagnóstico
    print("A correr diagnóstico rápido...")
    run_diagnostics(data)

    # 4) Procurar 1.ª solução viável por camadas
    print("A procurar a 1.ª solução válida dentro do tempo...")
    TOTAL_SECONDS = 90.0
    sol, by_class, soft_max3 = try_solve_with_budget(data, total_seconds=TOTAL_SECONDS)

    if not sol:
        print("\nNenhuma solução encontrada dentro do orçamento de tempo.")
        print("DICAS:")
        print(" - Se o 'DEBUG/TESTE: ignorar rooms e max3' encontrar solução → problema nas salas/limite diário/ordenação.")
        print(" - Se nem o debug/teste encontrar solução → conflito de indisponibilidades/carga ou dataset mal formado.")
        sys.exit(0)

    # 5) Score + Display
    sc = score_solution(sol, by_class, data, soft_max3=soft_max3)
    print("\n== SOLUÇÃO ENCONTRADA ==")
    print("Score (apenas indicativo):", sc)
    show_by_class(sol, by_class)
    show_by_teacher(sol, data)

    # 6) Exportação final
    export_all(sol, by_class, data, outdir="export")


if __name__ == "__main__":
    main()